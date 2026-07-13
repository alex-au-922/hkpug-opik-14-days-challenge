package helper

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
)

const (
	miniWorkshopProjectName     = "HKPUG Mini Workshop"
	miniWorkshopDatasetID       = "019f2fca-d8a8-7a1d-97df-31c4219eab5f"
	miniWorkshopDatasetName     = "HKPUG Prompt Release Review Suite"
	miniWorkshopTraceCount      = 6
	miniWorkshopSpanCount       = 43
	miniWorkshopTraceScoreCount = 23
	miniWorkshopSpanScoreCount  = 9
)

var miniWorkshopExperimentIDs = []string{
	"019f2fcb-0a67-75b3-ad91-cee989ee917f",
	"019f2fca-62b5-7c71-bd71-7f648c106d60",
}

type nativeFeaturesPayload struct {
	Dataset     nativeDataset      `json:"dataset"`
	Experiments []nativeExperiment `json:"experiments"`
}

type nativeDataset struct {
	ID          string            `json:"id"`
	Name        string            `json:"name"`
	Type        string            `json:"type"`
	Visibility  string            `json:"visibility"`
	Tags        json.RawMessage   `json:"tags"`
	Description string            `json:"description"`
	Items       []json.RawMessage `json:"items"`
}

type nativeExperiment struct {
	ID               string            `json:"id"`
	Name             string            `json:"name"`
	Metadata         json.RawMessage   `json:"metadata"`
	Tags             json.RawMessage   `json:"tags"`
	Type             string            `json:"type"`
	EvaluationMethod string            `json:"evaluation_method"`
	Status           string            `json:"status"`
	ExperimentScores json.RawMessage   `json:"experiment_scores"`
	Items            []json.RawMessage `json:"items"`
}

type nativeFeatureCounts struct {
	datasetCount        int
	datasetItemCount    int
	experimentCount     int
	experimentItemCount int
}

func parseNativeFeatures(payload []byte) (*nativeFeaturesPayload, error) {
	var native nativeFeaturesPayload
	if err := json.Unmarshal(payload, &native); err != nil {
		return nil, errors.New("payload is not valid JSON")
	}
	if native.Dataset.ID != miniWorkshopDatasetID || native.Dataset.Name != miniWorkshopDatasetName {
		return nil, errors.New("dataset is not the copied HKPUG mini-workshop dataset")
	}
	if strings.TrimSpace(native.Dataset.Type) == "" || strings.TrimSpace(native.Dataset.Visibility) == "" {
		return nil, errors.New("dataset type and visibility must be non-empty")
	}
	if len(native.Dataset.Items) != 6 {
		return nil, fmt.Errorf("copied mini-workshop dataset must contain 6 items, got %d", len(native.Dataset.Items))
	}
	if len(native.Experiments) != len(miniWorkshopExperimentIDs) {
		return nil, fmt.Errorf("copied mini-workshop data must contain 2 experiments, got %d", len(native.Experiments))
	}
	for index, experiment := range native.Experiments {
		if experiment.ID != miniWorkshopExperimentIDs[index] {
			return nil, fmt.Errorf("experiment %d has unexpected stable ID %q", index, experiment.ID)
		}
		if strings.TrimSpace(experiment.Name) == "" || strings.TrimSpace(experiment.Type) == "" || strings.TrimSpace(experiment.EvaluationMethod) == "" {
			return nil, fmt.Errorf("experiment %d has incomplete metadata", index)
		}
		if len(experiment.Items) != 6 {
			return nil, fmt.Errorf("experiment %q must contain 6 items, got %d", experiment.Name, len(experiment.Items))
		}
	}
	return &native, nil
}

func validateCopiedMiniWorkshop(
	native *nativeFeaturesPayload,
	payloads [][]byte,
	counts []int,
	projectName string,
) (string, error) {
	if len(payloads) != 4 || len(counts) != 4 {
		return "", errors.New("copied mini-workshop bundle is incomplete")
	}
	wantCounts := []int{
		miniWorkshopTraceCount,
		miniWorkshopSpanCount,
		miniWorkshopTraceScoreCount,
		miniWorkshopSpanScoreCount,
	}
	for index, count := range counts {
		if count != wantCounts[index] {
			return "", fmt.Errorf("copied mini-workshop payload %d has %d items, want %d", index, count, wantCounts[index])
		}
	}

	observedProject, err := collectionProjectName(payloads[0], "traces", "trace", "")
	if err != nil {
		return "", err
	}
	if projectName == "" {
		if observedProject != miniWorkshopProjectName {
			return "", fmt.Errorf("run.json is required for project %q", observedProject)
		}
		projectName = observedProject
	}
	if observedProject != projectName {
		return "", fmt.Errorf("traces use project %q, want %q", observedProject, projectName)
	}
	for index, spec := range []struct {
		collection string
		label      string
	}{
		{collection: "spans", label: "span"},
		{collection: "scores", label: "trace feedback"},
		{collection: "scores", label: "span feedback"},
	} {
		if _, err := collectionProjectName(payloads[index+1], spec.collection, spec.label, projectName); err != nil {
			return "", err
		}
	}
	if err := native.validateProjectName(projectName); err != nil {
		return "", err
	}
	return projectName, nil
}

func collectionProjectName(payload []byte, collection, label, expected string) (string, error) {
	var root map[string]json.RawMessage
	if err := json.Unmarshal(payload, &root); err != nil {
		return "", fmt.Errorf("%s payload is not valid JSON", label)
	}
	var items []struct {
		ProjectName string `json:"project_name"`
	}
	if err := json.Unmarshal(root[collection], &items); err != nil {
		return "", fmt.Errorf("%s payload must be an array", label)
	}
	projectName := expected
	for index, item := range items {
		if strings.TrimSpace(item.ProjectName) == "" {
			return "", fmt.Errorf("%s item %d project_name must be non-empty", label, index)
		}
		if projectName == "" {
			projectName = item.ProjectName
		}
		if item.ProjectName != projectName {
			return "", fmt.Errorf("%s item %d uses project %q, want %q", label, index, item.ProjectName, projectName)
		}
	}
	if projectName == "" {
		return "", fmt.Errorf("%s payload must not be empty", label)
	}
	return projectName, nil
}

func (native *nativeFeaturesPayload) validateProjectName(projectName string) error {
	for experimentIndex, experiment := range native.Experiments {
		for itemIndex, rawItem := range experiment.Items {
			var item struct {
				Trace struct {
					ProjectName string `json:"project_name"`
				} `json:"trace"`
			}
			if err := json.Unmarshal(rawItem, &item); err != nil || strings.TrimSpace(item.Trace.ProjectName) == "" {
				return fmt.Errorf("experiment %d item %d trace must declare project_name", experimentIndex, itemIndex)
			}
			if item.Trace.ProjectName != projectName {
				return fmt.Errorf("experiment %d item %d uses project %q, want %q", experimentIndex, itemIndex, item.Trace.ProjectName, projectName)
			}
		}
	}
	return nil
}

func importNativeFeatures(
	client *http.Client,
	baseURL, workspace, projectName string,
	native *nativeFeaturesPayload,
) (nativeFeatureCounts, error) {
	projectID, err := findProjectID(client, baseURL, workspace, projectName)
	if err != nil {
		return nativeFeatureCounts{}, err
	}
	experimentIDs := make([]string, len(native.Experiments))
	for index, experiment := range native.Experiments {
		experimentIDs[index] = experiment.ID
	}
	deleteExperiments, err := json.Marshal(map[string]any{"ids": experimentIDs})
	if err != nil {
		return nativeFeatureCounts{}, fmt.Errorf("encode experiment deletion: %w", err)
	}
	if _, err := executeOpikRequest(
		client,
		baseURL+"/v1/private/experiments/delete",
		http.MethodPost,
		deleteExperiments,
		workspace,
		http.StatusNotFound,
	); err != nil {
		return nativeFeatureCounts{}, err
	}
	if _, err := executeOpikRequest(
		client,
		baseURL+"/v1/private/datasets/"+url.PathEscape(native.Dataset.ID),
		http.MethodDelete,
		nil,
		workspace,
		http.StatusNotFound,
	); err != nil {
		return nativeFeatureCounts{}, err
	}

	if err := sendNativeJSON(client, baseURL+"/v1/private/datasets/", http.MethodPost, workspace, map[string]any{
		"id":          native.Dataset.ID,
		"name":        native.Dataset.Name,
		"project_id":  projectID,
		"type":        native.Dataset.Type,
		"visibility":  native.Dataset.Visibility,
		"tags":        native.Dataset.Tags,
		"description": native.Dataset.Description,
	}); err != nil {
		return nativeFeatureCounts{}, err
	}
	if err := sendNativeJSON(client, baseURL+"/v1/private/datasets/items", http.MethodPut, workspace, map[string]any{
		"dataset_name": native.Dataset.Name,
		"project_id":   projectID,
		"items":        native.Dataset.Items,
	}); err != nil {
		return nativeFeatureCounts{}, err
	}

	experimentItemCount := 0
	for _, experiment := range native.Experiments {
		if err := sendNativeJSON(client, baseURL+"/v1/private/experiments/", http.MethodPost, workspace, map[string]any{
			"id":                experiment.ID,
			"dataset_name":      native.Dataset.Name,
			"project_id":        projectID,
			"name":              experiment.Name,
			"metadata":          experiment.Metadata,
			"tags":              experiment.Tags,
			"type":              experiment.Type,
			"evaluation_method": experiment.EvaluationMethod,
			"status":            experiment.Status,
			"experiment_scores": experiment.ExperimentScores,
		}); err != nil {
			return nativeFeatureCounts{}, err
		}
		if err := sendNativeJSON(client, baseURL+"/v1/private/experiments/items/bulk", http.MethodPut, workspace, map[string]any{
			"experiment_name": experiment.Name,
			"dataset_name":    native.Dataset.Name,
			"experiment_id":   experiment.ID,
			"project_name":    projectName,
			"items":           experiment.Items,
		}); err != nil {
			return nativeFeatureCounts{}, err
		}
		experimentItemCount += len(experiment.Items)
	}
	if err := sendNativeJSON(client, baseURL+"/v1/private/experiments/finish", http.MethodPost, workspace, map[string]any{
		"ids": experimentIDs,
	}); err != nil {
		return nativeFeatureCounts{}, err
	}
	return nativeFeatureCounts{
		datasetCount:        1,
		datasetItemCount:    len(native.Dataset.Items),
		experimentCount:     len(native.Experiments),
		experimentItemCount: experimentItemCount,
	}, nil
}

func findProjectID(client *http.Client, baseURL, workspace, projectName string) (string, error) {
	workspaceName := workspace
	if workspaceName == "" {
		workspaceName = "default"
	}
	query := url.Values{
		"workspace_name": {workspaceName},
		"size":           {"1000"},
		"page":           {"1"},
	}
	payload, err := executeOpikRequest(
		client,
		baseURL+"/v1/private/projects/?"+query.Encode(),
		http.MethodGet,
		nil,
		workspace,
	)
	if err != nil {
		return "", err
	}
	var response struct {
		Content []struct {
			ID   string `json:"id"`
			Name string `json:"name"`
		} `json:"content"`
	}
	if err := json.Unmarshal(payload, &response); err != nil {
		return "", errors.New("Opik projects response is not valid JSON")
	}
	for _, project := range response.Content {
		if project.Name == projectName && strings.TrimSpace(project.ID) != "" {
			return project.ID, nil
		}
	}
	return "", fmt.Errorf("Opik project %q was not found in workspace %q", projectName, workspaceName)
}

func sendNativeJSON(client *http.Client, requestURL, method, workspace string, value any) error {
	payload, err := json.Marshal(value)
	if err != nil {
		return fmt.Errorf("encode native Opik payload: %w", err)
	}
	return sendOpikRequest(client, requestURL, method, payload, workspace)
}
