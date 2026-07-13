package helper

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const maxOpikPayloadBytes = 64 * 1024 * 1024

type LoadOpikOptions struct {
	FeedbackDirectory string
	BaseURL           string
	Workspace         string
	Client            *http.Client
}

type LoadOpikResult struct {
	ProjectName         string `json:"project_name"`
	TraceCount          int    `json:"trace_count"`
	SpanCount           int    `json:"span_count"`
	TraceFeedbackCount  int    `json:"trace_feedback_count"`
	SpanFeedbackCount   int    `json:"span_feedback_count"`
	DatasetCount        int    `json:"dataset_count,omitempty"`
	DatasetItemCount    int    `json:"dataset_item_count,omitempty"`
	ExperimentCount     int    `json:"experiment_count,omitempty"`
	ExperimentItemCount int    `json:"experiment_item_count,omitempty"`
}

func LoadOpik(options LoadOpikOptions) (LoadOpikResult, error) {
	if options.FeedbackDirectory == "" {
		return LoadOpikResult{}, errors.New("feedback directory is required")
	}
	if options.BaseURL == "" {
		options.BaseURL = "http://localhost:5173/api"
	}
	baseURL, err := url.Parse(options.BaseURL)
	if err != nil || (baseURL.Scheme != "http" && baseURL.Scheme != "https") || baseURL.Host == "" {
		return LoadOpikResult{}, errors.New("Opik URL must be an absolute HTTP or HTTPS URL")
	}
	if baseURL.User != nil || baseURL.RawQuery != "" || baseURL.Fragment != "" {
		return LoadOpikResult{}, errors.New("Opik URL must not contain credentials, a query, or a fragment")
	}

	nativePayload, hasNativeFeatures, err := readOptionalJSONFile(options.FeedbackDirectory, "native_features.json")
	if err != nil {
		return LoadOpikResult{}, err
	}
	var nativeFeatures *nativeFeaturesPayload
	if hasNativeFeatures {
		nativeFeatures, err = parseNativeFeatures(nativePayload)
		if err != nil {
			return LoadOpikResult{}, fmt.Errorf("native_features.json: %w", err)
		}
	}

	runPayload, hasRun, err := readOptionalJSONFile(options.FeedbackDirectory, "run.json")
	if err != nil {
		return LoadOpikResult{}, err
	}
	if !hasRun && nativeFeatures == nil {
		runPayload, err = readJSONFile(options.FeedbackDirectory, "run.json")
		if err != nil {
			return LoadOpikResult{}, err
		}
		hasRun = true
	}
	projectName := ""
	if hasRun {
		projectName, err = validateDiscoveryRun(runPayload)
		if err != nil {
			return LoadOpikResult{}, err
		}
	}

	type requestSpec struct {
		method     string
		path       string
		filename   string
		collection string
		discovery  bool
	}
	requests := []requestSpec{
		{method: http.MethodPost, path: "/v1/private/traces/batch", filename: "trace_payload.json", collection: "traces", discovery: true},
		{method: http.MethodPost, path: "/v1/private/spans/batch", filename: "span_payload.json", collection: "spans", discovery: true},
		{method: http.MethodPut, path: "/v1/private/traces/feedback-scores", filename: "trace_feedback.json", collection: "scores"},
		{method: http.MethodPut, path: "/v1/private/spans/feedback-scores", filename: "span_feedback.json", collection: "scores"},
	}
	counts := make([]int, 0, len(requests))
	payloads := make([][]byte, 0, len(requests))
	for _, request := range requests {
		payload, err := readJSONFile(options.FeedbackDirectory, request.filename)
		if err != nil {
			return LoadOpikResult{}, err
		}
		count, err := validateCollection(payload, request.collection, request.discovery && nativeFeatures == nil)
		if err != nil {
			return LoadOpikResult{}, fmt.Errorf("%s: %w", request.filename, err)
		}
		payloads = append(payloads, payload)
		counts = append(counts, count)
	}
	if nativeFeatures != nil {
		projectName, err = validateCopiedMiniWorkshop(nativeFeatures, payloads, counts, projectName)
		if err != nil {
			return LoadOpikResult{}, fmt.Errorf("native_features.json: %w", err)
		}
	}

	client := options.Client
	if client == nil {
		client = &http.Client{Timeout: 30 * time.Second}
	}
	for index, request := range requests {
		if err := sendOpikRequest(
			client,
			strings.TrimRight(options.BaseURL, "/")+request.path,
			request.method,
			payloads[index],
			options.Workspace,
		); err != nil {
			return LoadOpikResult{}, err
		}
	}
	result := LoadOpikResult{
		ProjectName:        projectName,
		TraceCount:         counts[0],
		SpanCount:          counts[1],
		TraceFeedbackCount: counts[2],
		SpanFeedbackCount:  counts[3],
	}
	if nativeFeatures != nil {
		nativeCounts, err := importNativeFeatures(
			client,
			strings.TrimRight(options.BaseURL, "/"),
			options.Workspace,
			projectName,
			nativeFeatures,
		)
		if err != nil {
			return LoadOpikResult{}, err
		}
		result.DatasetCount = nativeCounts.datasetCount
		result.DatasetItemCount = nativeCounts.datasetItemCount
		result.ExperimentCount = nativeCounts.experimentCount
		result.ExperimentItemCount = nativeCounts.experimentItemCount
	}
	return result, nil
}

func readOptionalJSONFile(directory, filename string) ([]byte, bool, error) {
	path := filepath.Join(directory, filename)
	if _, err := os.Lstat(path); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, false, nil
		}
		return nil, false, fmt.Errorf("read feedback file %s: %w", filename, err)
	}
	payload, err := readJSONFile(directory, filename)
	if err != nil {
		return nil, false, err
	}
	return payload, true, nil
}

func readJSONFile(directory, filename string) ([]byte, error) {
	path := filepath.Join(directory, filename)
	info, err := os.Lstat(path)
	if err != nil {
		return nil, fmt.Errorf("read feedback file %s: %w", filename, err)
	}
	if !info.Mode().IsRegular() || info.Size() <= 0 || info.Size() > maxOpikPayloadBytes {
		return nil, fmt.Errorf("feedback file %s must be a bounded regular file", filename)
	}
	payload, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read feedback file %s: %w", filename, err)
	}
	return payload, nil
}

func validateDiscoveryRun(payload []byte) (string, error) {
	var run map[string]json.RawMessage
	if err := json.Unmarshal(payload, &run); err != nil {
		return "", errors.New("run.json is not valid JSON")
	}
	var schemaVersion int
	var partition string
	var projectName string
	if err := json.Unmarshal(run["schema_version"], &schemaVersion); err != nil || schemaVersion != 1 {
		return "", errors.New("run.json schema_version must be 1")
	}
	if err := json.Unmarshal(run["bundle_partition"], &partition); err != nil || partition != "discovery" {
		return "", errors.New("only discovery feedback bundles can be loaded")
	}
	if err := json.Unmarshal(run["project_name"], &projectName); err != nil || strings.TrimSpace(projectName) == "" {
		return "", errors.New("run.json project_name must be non-empty")
	}
	for key := range run {
		if strings.HasPrefix(strings.ToLower(key), "holdout") && key != "holdout" {
			return "", errors.New("run.json must contain aggregate holdout data only")
		}
	}
	var holdout map[string]json.RawMessage
	if err := json.Unmarshal(run["holdout"], &holdout); err != nil {
		return "", errors.New("run.json holdout must be an aggregate object")
	}
	if len(holdout) != 3 || holdout["case_count"] == nil || holdout["criteria"] == nil || holdout["score"] == nil {
		return "", errors.New("run.json holdout must contain only case_count, criteria, and score")
	}
	return projectName, nil
}

func validateCollection(payload []byte, collection string, discovery bool) (int, error) {
	var object map[string]json.RawMessage
	if err := json.Unmarshal(payload, &object); err != nil {
		return 0, errors.New("payload is not valid JSON")
	}
	if len(object) != 1 || object[collection] == nil {
		return 0, fmt.Errorf("payload must contain only %q", collection)
	}
	var items []map[string]json.RawMessage
	if err := json.Unmarshal(object[collection], &items); err != nil {
		return 0, fmt.Errorf("payload %q must be an array of objects", collection)
	}
	if discovery {
		for _, item := range items {
			var metadata map[string]json.RawMessage
			if err := json.Unmarshal(item["metadata"], &metadata); err != nil {
				return 0, fmt.Errorf("every %s item must declare discovery metadata", collection)
			}
			var partition string
			if err := json.Unmarshal(metadata["partition"], &partition); err != nil || partition != "discovery" {
				return 0, fmt.Errorf("every %s item must declare metadata.partition=discovery", collection)
			}
		}
	}
	return len(items), nil
}

func sendOpikRequest(client *http.Client, requestURL, method string, payload []byte, workspace string) error {
	_, err := executeOpikRequest(client, requestURL, method, payload, workspace)
	return err
}

func executeOpikRequest(
	client *http.Client,
	requestURL, method string,
	payload []byte,
	workspace string,
	allowedStatuses ...int,
) ([]byte, error) {
	request, err := http.NewRequest(method, requestURL, bytes.NewReader(payload))
	if err != nil {
		return nil, fmt.Errorf("create Opik request: %w", err)
	}
	request.Header.Set("Accept", "application/json")
	request.Header.Set("Content-Type", "application/json")
	if workspace != "" {
		request.Header.Set("Comet-Workspace-Name", workspace)
	}
	response, err := client.Do(request)
	if err != nil {
		return nil, fmt.Errorf("send Opik request: %w", err)
	}
	defer response.Body.Close()
	allowed := response.StatusCode >= 200 && response.StatusCode < 300
	for _, status := range allowedStatuses {
		allowed = allowed || response.StatusCode == status
	}
	if !allowed {
		detail, _ := io.ReadAll(io.LimitReader(response.Body, 1024))
		return nil, fmt.Errorf("Opik %s returned %d: %s", request.URL.Path, response.StatusCode, strings.TrimSpace(string(detail)))
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxOpikPayloadBytes+1))
	if err != nil {
		return nil, fmt.Errorf("read Opik %s response: %w", request.URL.Path, err)
	}
	if len(body) > maxOpikPayloadBytes {
		return nil, fmt.Errorf("Opik %s response exceeds the size limit", request.URL.Path)
	}
	return body, nil
}
