package helper

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

const (
	testDatasetID     = "019f2fca-d8a8-7a1d-97df-31c4219eab5f"
	testExperimentOne = "019f2fcb-0a67-75b3-ad91-cee989ee917f"
	testExperimentTwo = "019f2fca-62b5-7c71-bd71-7f648c106d60"
	testProjectName   = "HKPUG Mini Workshop"
)

type recordedOpikRequest struct {
	method    string
	path      string
	rawQuery  string
	workspace string
	body      []byte
	payload   map[string]any
}

func TestLoadOpikImportsCopiedMiniWorkshopExactly(t *testing.T) {
	t.Parallel()

	requests := make([]recordedOpikRequest, 0)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Errorf("read request body: %v", err)
		}
		payload := map[string]any{}
		if len(body) > 0 {
			if err := json.Unmarshal(body, &payload); err != nil {
				t.Errorf("decode %s %s body: %v", request.Method, request.URL.Path, err)
			}
		}
		requests = append(requests, recordedOpikRequest{
			method:    request.Method,
			path:      request.URL.Path,
			rawQuery:  request.URL.RawQuery,
			workspace: request.Header.Get("Comet-Workspace-Name"),
			body:      body,
			payload:   payload,
		})

		if request.Method == http.MethodGet && request.URL.Path == "/api/v1/private/projects/" {
			writer.Header().Set("Content-Type", "application/json")
			if err := json.NewEncoder(writer).Encode(map[string]any{
				"content": []any{map[string]any{"id": "project-id", "name": testProjectName}},
			}); err != nil {
				t.Errorf("encode project response: %v", err)
			}
			return
		}
		if request.Method == http.MethodDelete && request.URL.Path == "/api/v1/private/datasets/"+testDatasetID {
			writer.WriteHeader(http.StatusNotFound)
			return
		}
		writer.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	directory := copiedMiniWorkshopDirectory(t)
	result, err := LoadOpik(LoadOpikOptions{
		FeedbackDirectory: directory,
		BaseURL:           server.URL + "/api",
		Workspace:         "default",
		Client:            server.Client(),
	})
	if err != nil {
		t.Fatalf("LoadOpik returned an error: %v", err)
	}
	encodedResult, err := json.Marshal(result)
	if err != nil {
		t.Fatal(err)
	}
	var output map[string]any
	if err := json.Unmarshal(encodedResult, &output); err != nil {
		t.Fatal(err)
	}
	for key, want := range map[string]float64{
		"trace_count":           6,
		"span_count":            43,
		"trace_feedback_count":  23,
		"span_feedback_count":   9,
		"dataset_count":         1,
		"dataset_item_count":    6,
		"experiment_count":      2,
		"experiment_item_count": 12,
	} {
		if output[key] != want {
			t.Errorf("result %s = %#v, want %v", key, output[key], want)
		}
	}

	wantRequests := []string{
		"POST /api/v1/private/traces/batch",
		"POST /api/v1/private/spans/batch",
		"PUT /api/v1/private/traces/feedback-scores",
		"PUT /api/v1/private/spans/feedback-scores",
		"GET /api/v1/private/projects/",
		"POST /api/v1/private/experiments/delete",
		"DELETE /api/v1/private/datasets/" + testDatasetID,
		"POST /api/v1/private/datasets/",
		"PUT /api/v1/private/datasets/items",
		"POST /api/v1/private/experiments/",
		"PUT /api/v1/private/experiments/items/bulk",
		"POST /api/v1/private/experiments/",
		"PUT /api/v1/private/experiments/items/bulk",
		"POST /api/v1/private/experiments/finish",
	}
	gotRequests := make([]string, len(requests))
	for index, request := range requests {
		gotRequests[index] = request.method + " " + request.path
		if request.workspace != "default" {
			t.Errorf("request %d workspace = %q, want default", index, request.workspace)
		}
	}
	if !reflect.DeepEqual(gotRequests, wantRequests) {
		t.Fatalf("requests = %v, want %v", gotRequests, wantRequests)
	}
	if requests[4].rawQuery != "page=1&size=1000&workspace_name=default" {
		t.Errorf("project query = %q", requests[4].rawQuery)
	}

	for index, filename := range []string{
		"trace_payload.json",
		"span_payload.json",
		"trace_feedback.json",
		"span_feedback.json",
	} {
		want, err := os.ReadFile(filepath.Join(directory, filename))
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(requests[index].body, want) {
			t.Errorf("%s was not replayed byte-for-byte", filename)
		}
	}

	native := readJSONObject(t, filepath.Join(directory, "native_features.json"))
	dataset := mustObjectField(t, native, "dataset")
	experiments := mustArrayField(t, native, "experiments")
	wantDatasetCreate := map[string]any{
		"id":          dataset["id"],
		"name":        dataset["name"],
		"project_id":  "project-id",
		"type":        dataset["type"],
		"visibility":  dataset["visibility"],
		"tags":        dataset["tags"],
		"description": dataset["description"],
	}
	assertPayloadEqual(t, requests[7].payload, wantDatasetCreate)
	assertPayloadEqual(t, requests[8].payload, map[string]any{
		"dataset_name": dataset["name"],
		"project_id":   "project-id",
		"items":        dataset["items"],
	})

	experimentIDs := make([]string, len(experiments))
	for index, rawExperiment := range experiments {
		experiment, ok := rawExperiment.(map[string]any)
		if !ok {
			t.Fatalf("experiment %d = %#v, want object", index, rawExperiment)
		}
		experimentIDs[index], _ = experiment["id"].(string)
		createRequest := requests[9+index*2]
		bulkRequest := requests[10+index*2]
		assertPayloadEqual(t, createRequest.payload, map[string]any{
			"id":                experiment["id"],
			"dataset_name":      dataset["name"],
			"project_id":        "project-id",
			"name":              experiment["name"],
			"metadata":          experiment["metadata"],
			"tags":              experiment["tags"],
			"type":              experiment["type"],
			"evaluation_method": experiment["evaluation_method"],
			"status":            experiment["status"],
			"experiment_scores": experiment["experiment_scores"],
		})
		assertPayloadEqual(t, bulkRequest.payload, map[string]any{
			"experiment_name": experiment["name"],
			"dataset_name":    dataset["name"],
			"experiment_id":   experiment["id"],
			"project_name":    testProjectName,
			"items":           experiment["items"],
		})
	}
	if !reflect.DeepEqual(experimentIDs, []string{testExperimentOne, testExperimentTwo}) {
		t.Fatalf("fixture experiment IDs = %v", experimentIDs)
	}
	if got := mustStringArrayField(t, requests[5].payload, "ids"); !reflect.DeepEqual(got, experimentIDs) {
		t.Errorf("deleted experiment IDs = %v, want %v", got, experimentIDs)
	}
	if got := mustStringArrayField(t, requests[13].payload, "ids"); !reflect.DeepEqual(got, experimentIDs) {
		t.Errorf("finished experiment IDs = %v, want %v", got, experimentIDs)
	}
}

func TestLoadOpikAcceptsDiscoveryRunAroundCopiedMiniWorkshop(t *testing.T) {
	t.Parallel()

	directory := t.TempDir()
	copyMiniWorkshopPayloads(t, directory)
	writeJSON(t, directory, "run.json", map[string]any{
		"schema_version":   1,
		"bundle_partition": "discovery",
		"project_name":     testProjectName,
		"holdout": map[string]any{
			"case_count": 0,
			"criteria":   map[string]any{},
			"score":      0,
		},
	})
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		switch {
		case request.Method == http.MethodGet && request.URL.Path == "/api/v1/private/projects/":
			_ = json.NewEncoder(writer).Encode(map[string]any{
				"content": []any{map[string]any{"id": "project-id", "name": testProjectName}},
			})
		case request.Method == http.MethodDelete && request.URL.Path == "/api/v1/private/datasets/"+testDatasetID:
			writer.WriteHeader(http.StatusNotFound)
		default:
			writer.WriteHeader(http.StatusNoContent)
		}
	}))
	defer server.Close()

	result, err := LoadOpik(LoadOpikOptions{
		FeedbackDirectory: directory,
		BaseURL:           server.URL + "/api",
		Workspace:         "default",
		Client:            server.Client(),
	})
	if err != nil {
		t.Fatalf("LoadOpik returned an error: %v", err)
	}
	if result.TraceCount != 6 || result.ExperimentCount != 2 {
		t.Fatalf("result = %#v", result)
	}
}

func TestLoadOpikCanReloadCopiedMiniWorkshop(t *testing.T) {
	t.Parallel()

	datasetExists := false
	experiments := map[string]bool{}
	datasetCreates := 0
	experimentCreates := 0
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var payload map[string]any
		if request.Body != nil {
			if err := json.NewDecoder(request.Body).Decode(&payload); err != nil && err != io.EOF {
				t.Errorf("decode %s %s: %v", request.Method, request.URL.Path, err)
				writer.WriteHeader(http.StatusBadRequest)
				return
			}
		}
		switch {
		case request.Method == http.MethodGet && request.URL.Path == "/api/v1/private/projects/":
			_ = json.NewEncoder(writer).Encode(map[string]any{
				"content": []any{map[string]any{"id": "project-id", "name": testProjectName}},
			})
		case request.Method == http.MethodPost && request.URL.Path == "/api/v1/private/experiments/delete":
			rawIDs, ok := payload["ids"].([]any)
			if !ok {
				t.Errorf("delete experiment IDs = %#v, want array", payload["ids"])
				writer.WriteHeader(http.StatusBadRequest)
				return
			}
			for _, rawID := range rawIDs {
				id, ok := rawID.(string)
				if !ok {
					t.Errorf("delete experiment ID = %#v, want string", rawID)
					writer.WriteHeader(http.StatusBadRequest)
					return
				}
				delete(experiments, id)
			}
			writer.WriteHeader(http.StatusNoContent)
		case request.Method == http.MethodDelete && request.URL.Path == "/api/v1/private/datasets/"+testDatasetID:
			if !datasetExists {
				writer.WriteHeader(http.StatusNotFound)
				return
			}
			datasetExists = false
			writer.WriteHeader(http.StatusNoContent)
		case request.Method == http.MethodPost && request.URL.Path == "/api/v1/private/datasets/":
			if datasetExists {
				http.Error(writer, "duplicate dataset", http.StatusConflict)
				return
			}
			datasetExists = true
			datasetCreates++
			writer.WriteHeader(http.StatusCreated)
		case request.Method == http.MethodPost && request.URL.Path == "/api/v1/private/experiments/":
			id, _ := payload["id"].(string)
			if experiments[id] {
				http.Error(writer, "duplicate experiment", http.StatusConflict)
				return
			}
			experiments[id] = true
			experimentCreates++
			writer.WriteHeader(http.StatusCreated)
		default:
			writer.WriteHeader(http.StatusNoContent)
		}
	}))
	defer server.Close()

	options := LoadOpikOptions{
		FeedbackDirectory: copiedMiniWorkshopDirectory(t),
		BaseURL:           server.URL + "/api",
		Workspace:         "default",
		Client:            server.Client(),
	}
	for attempt := 1; attempt <= 2; attempt++ {
		if _, err := LoadOpik(options); err != nil {
			t.Fatalf("LoadOpik attempt %d returned an error: %v", attempt, err)
		}
	}
	if datasetCreates != 2 {
		t.Errorf("dataset creates = %d, want 2", datasetCreates)
	}
	if experimentCreates != 4 {
		t.Errorf("experiment creates = %d, want 4", experimentCreates)
	}
	if !datasetExists || len(experiments) != 2 {
		t.Errorf("final resources: dataset=%t experiments=%v", datasetExists, experiments)
	}
}

func copiedMiniWorkshopDirectory(t *testing.T) string {
	t.Helper()
	directory := filepath.Join("..", "onboarding", "mini-workshop", "opik")
	for _, filename := range []string{
		"trace_payload.json",
		"span_payload.json",
		"trace_feedback.json",
		"span_feedback.json",
		"native_features.json",
	} {
		if _, err := os.Stat(filepath.Join(directory, filename)); err != nil {
			t.Fatalf("copied mini-workshop fixture %s: %v", filename, err)
		}
	}
	return directory
}

func copyMiniWorkshopPayloads(t *testing.T, destination string) {
	t.Helper()
	source := copiedMiniWorkshopDirectory(t)
	for _, filename := range []string{
		"trace_payload.json",
		"span_payload.json",
		"trace_feedback.json",
		"span_feedback.json",
		"native_features.json",
	} {
		payload, err := os.ReadFile(filepath.Join(source, filename))
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(destination, filename), payload, 0o600); err != nil {
			t.Fatal(err)
		}
	}
}

func readJSONObject(t *testing.T, path string) map[string]any {
	t.Helper()
	payload, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var object map[string]any
	if err := json.Unmarshal(payload, &object); err != nil {
		t.Fatal(err)
	}
	return object
}

func assertPayloadEqual(t *testing.T, got, want map[string]any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		gotJSON, _ := json.Marshal(got)
		wantJSON, _ := json.Marshal(want)
		t.Errorf("payload = %s, want %s", gotJSON, wantJSON)
	}
}

func mustObjectField(t *testing.T, object map[string]any, key string) map[string]any {
	t.Helper()
	value, ok := object[key].(map[string]any)
	if !ok {
		t.Fatalf("%s = %#v, want object", key, object[key])
	}
	return value
}

func mustArrayField(t *testing.T, object map[string]any, key string) []any {
	t.Helper()
	values, ok := object[key].([]any)
	if !ok {
		t.Fatalf("%s = %#v, want array", key, object[key])
	}
	return values
}

func mustStringArrayField(t *testing.T, object map[string]any, key string) []string {
	t.Helper()
	values := mustArrayField(t, object, key)
	result := make([]string, len(values))
	for index, value := range values {
		text, ok := value.(string)
		if !ok {
			t.Fatalf("%s[%d] = %#v, want string", key, index, value)
		}
		result[index] = text
	}
	return result
}
