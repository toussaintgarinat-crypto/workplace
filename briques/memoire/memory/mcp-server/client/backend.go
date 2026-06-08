package client

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/go-resty/resty/v2"
)

type Client struct {
	client  *resty.Client
	baseURL string
	token   string
}

func New(baseURL, token string) *Client {
	c := resty.New().
		SetBaseURL(baseURL + "/api/v1").
		SetTimeout(30 * time.Second).
		SetHeader("Authorization", "Bearer "+token).
		SetHeader("Content-Type", "application/json")

	return &Client{
		client:  c,
		baseURL: baseURL + "/api/v1",
		token:   token,
	}
}

type Node struct {
	ID          string                 `json:"id"`
	SpaceID     string                 `json:"space_id"`
	Type        string                 `json:"type"`
	IpCraStage  string                 `json:"ipcra_stage"`
	StorageTier string                 `json:"storage_tier"`
	Status      string                 `json:"status"`
	Title       string                 `json:"title"`
	ContentMD   string                 `json:"content_md"`
	Frontmatter map[string]interface{} `json:"frontmatter"`
	CreatedAt   string                 `json:"created_at"`
	UpdatedAt   string                 `json:"updated_at"`
}

type CreateNodeRequest struct {
	Title       string                 `json:"title"`
	ContentMD   string                 `json:"content_md"`
	Type        string                 `json:"type"`
	Frontmatter map[string]interface{} `json:"frontmatter,omitempty"`
	SourceURL   string                 `json:"source_url,omitempty"`
	CapturedFrom string                `json:"captured_from,omitempty"`
	Location    map[string]string      `json:"location,omitempty"`
}

type SearchResultItem struct {
	ID          string                 `json:"id"`
	Title       string                 `json:"title"`
	ContentMD   string                 `json:"content_md"`
	Type        string                 `json:"type"`
	StorageTier string                 `json:"storage_tier"`
	Score       float64                `json:"score"`
	HappenedAt  string                 `json:"happened_at"`
}

type Edge struct {
	ID        string  `json:"id"`
	SourceID  string  `json:"source_id"`
	TargetID  string  `json:"target_id"`
	Type      string  `json:"type"`
	Weight    float64 `json:"weight"`
}

type GraphResponse struct {
	Nodes []Node `json:"nodes"`
	Edges []Edge `json:"edges"`
}

type GardienSuggestion struct {
	ID        string                 `json:"id"`
	Action    string                 `json:"action"`
	NodeID    string                 `json:"node_id"`
	Details   map[string]interface{} `json:"details"`
	Status    string                 `json:"status"`
	CreatedAt string                 `json:"created_at"`
}

type AgingNode struct {
	ID          string  `json:"id"`
	Title       string  `json:"title"`
	StorageTier string  `json:"storage_tier"`
}

type StatsResponse struct {
	TotalNodes int            `json:"total_nodes"`
	ByType     map[string]int `json:"by_type"`
	ByStage    map[string]int `json:"by_stage"`
	ByTier     map[string]int `json:"by_tier"`
}

type Space struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Description string `json:"description"`
}

func (c *Client) ListSpaces() ([]Space, error) {
	var spaces []Space
	resp, err := c.client.R().SetResult(&spaces).Get("/spaces")
	if err != nil {
		return nil, fmt.Errorf("list spaces: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("list spaces: status %d", resp.StatusCode())
	}
	return spaces, nil
}

func (c *Client) CreateNode(spaceID string, req CreateNodeRequest) (*Node, error) {
	var node Node
	resp, err := c.client.R().
		SetBody(req).
		SetResult(&node).
		Post("/spaces/" + spaceID + "/nodes")
	if err != nil {
		return nil, fmt.Errorf("create node: %w", err)
	}
	if resp.StatusCode() != http.StatusCreated {
		return nil, fmt.Errorf("create node: status %d: %s", resp.StatusCode(), resp.String())
	}
	return &node, nil
}

func (c *Client) GetNode(spaceID, nodeID string) (*Node, error) {
	var node Node
	resp, err := c.client.R().
		SetResult(&node).
		Get("/spaces/" + spaceID + "/nodes/" + nodeID)
	if err != nil {
		return nil, fmt.Errorf("get node: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("get node: status %d", resp.StatusCode())
	}
	return &node, nil
}

func (c *Client) Search(spaceID, query string, limit int, typeFilter string) ([]SearchResultItem, error) {
	var result []SearchResultItem
	req := c.client.R().SetResult(&result)
	if query != "" {
		req.SetQueryParam("q", query)
	}
	if limit > 0 {
		req.SetQueryParam("limit", fmt.Sprintf("%d", limit))
	}
	if typeFilter != "" {
		req.SetQueryParam("type", typeFilter)
	}
	resp, err := req.Get("/spaces/" + spaceID + "/search")
	if err != nil {
		return nil, fmt.Errorf("search: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("search: status %d", resp.StatusCode())
	}
	return result, nil
}

func (c *Client) SemanticSearch(spaceID, query string, limit int, stageFilter, typeFilter string) ([]SearchResultItem, error) {
	body := map[string]interface{}{
		"query": query,
	}
	if limit > 0 {
		body["limit"] = limit
	}
	if stageFilter != "" {
		body["stage_filter"] = stageFilter
	}
	if typeFilter != "" {
		body["type_filter"] = typeFilter
	}

	var result []SearchResultItem
	resp, err := c.client.R().
		SetBody(body).
		SetResult(&result).
		Post("/spaces/" + spaceID + "/search/semantic")
	if err != nil {
		return nil, fmt.Errorf("semantic search: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("semantic search: status %d", resp.StatusCode())
	}
	return result, nil
}

func (c *Client) GetGraph(spaceID, rootID string, depth int) (*GraphResponse, error) {
	var result GraphResponse
	req := c.client.R().SetResult(&result)
	if rootID != "" {
		req.SetQueryParam("root", rootID)
	}
	if depth > 0 {
		req.SetQueryParam("depth", fmt.Sprintf("%d", depth))
	}
	resp, err := req.Get("/spaces/" + spaceID + "/graph")
	if err != nil {
		return nil, fmt.Errorf("get graph: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("get graph: status %d", resp.StatusCode())
	}
	return &result, nil
}

func (c *Client) FindPath(spaceID, sourceID, targetID string) ([]Node, error) {
	var result []Node
	resp, err := c.client.R().
		SetQueryParam("source", sourceID).
		SetQueryParam("target", targetID).
		SetResult(&result).
		Get("/spaces/" + spaceID + "/graph/path")
	if err != nil {
		return nil, fmt.Errorf("find path: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("find path: status %d", resp.StatusCode())
	}
	return result, nil
}

func (c *Client) UpdateStage(spaceID, nodeID, stage, reason string) (*Node, error) {
	body := map[string]interface{}{
		"stage": stage,
	}
	if reason != "" {
		body["reason"] = reason
	}
	var node Node
	resp, err := c.client.R().
		SetBody(body).
		SetResult(&node).
		Patch("/spaces/" + spaceID + "/nodes/" + nodeID + "/stage")
	if err != nil {
		return nil, fmt.Errorf("update stage: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("update stage: status %d", resp.StatusCode())
	}
	return &node, nil
}

func (c *Client) RunGardien(spaceID string) (map[string]interface{}, error) {
	var result map[string]interface{}
	resp, err := c.client.R().
		SetResult(&result).
		Post("/spaces/" + spaceID + "/gardien/run")
	if err != nil {
		return nil, fmt.Errorf("run gardien: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("run gardien: status %d", resp.StatusCode())
	}
	return result, nil
}

func (c *Client) GetGardienSuggestions(spaceID string) ([]GardienSuggestion, error) {
	var suggestions []GardienSuggestion
	resp, err := c.client.R().
		SetResult(&suggestions).
		Get("/spaces/" + spaceID + "/gardien/suggestions")
	if err != nil {
		return nil, fmt.Errorf("get gardien suggestions: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("get gardien suggestions: status %d", resp.StatusCode())
	}
	return suggestions, nil
}

func (c *Client) GetAgingNodes(spaceID string) ([]AgingNode, error) {
	var nodes []AgingNode
	resp, err := c.client.R().
		SetResult(&nodes).
		Get("/spaces/" + spaceID + "/nodes/aging")
	if err != nil {
		return nil, fmt.Errorf("get aging: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("get aging: status %d", resp.StatusCode())
	}
	return nodes, nil
}

func (c *Client) GetStats(spaceID string) (*StatsResponse, error) {
	var stats StatsResponse
	resp, err := c.client.R().
		SetResult(&stats).
		Get("/spaces/" + spaceID + "/stats")
	if err != nil {
		return nil, fmt.Errorf("get stats: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("get stats: status %d, body: %s", resp.StatusCode(), resp.String())
	}
	return &stats, nil
}

type SpaceInfo struct {
	Space       Space                 `json:"space"`
	TotalNodes  int                   `json:"total_nodes"`
	ByType      map[string]int        `json:"by_type"`
	ByStage     map[string]int        `json:"by_stage"`
	ByTier      map[string]int        `json:"by_tier"`
	Aging       []AgingNode           `json:"aging"`
	Suggestions []GardienSuggestion  `json:"suggestions"`
}

func (c *Client) GetSpaceInfo(spaceID string) (*SpaceInfo, error) {
	var space Space
	resp, err := c.client.R().SetResult(&space).Get("/spaces/" + spaceID)
	if err != nil {
		return nil, fmt.Errorf("get space info: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("get space info: status %d", resp.StatusCode())
	}

	stats, err := c.GetStats(spaceID)
	if err != nil {
		stats = &StatsResponse{}
	}

	aging, err := c.GetAgingNodes(spaceID)
	if err != nil {
		aging = []AgingNode{}
	}

	suggestions, err := c.GetGardienSuggestions(spaceID)
	if err != nil {
		suggestions = []GardienSuggestion{}
	}

	info := &SpaceInfo{
		Space:       space,
		TotalNodes:  stats.TotalNodes,
		ByType:      stats.ByType,
		ByStage:     stats.ByStage,
		ByTier:      stats.ByTier,
		Aging:       aging,
		Suggestions: suggestions,
	}

	return info, nil
}

func (c *Client) CreateEdge(spaceID, sourceID, targetID, edgeType string) (*Edge, error) {
	body := map[string]interface{}{
		"source_id": sourceID,
		"target_id": targetID,
		"type":      edgeType,
	}
	var edge Edge
	resp, err := c.client.R().
		SetBody(body).
		SetResult(&edge).
		Post("/spaces/" + spaceID + "/graph/edges")
	if err != nil {
		return nil, fmt.Errorf("create edge: %w", err)
	}
	if resp.StatusCode() != http.StatusCreated && resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("create edge: status %d", resp.StatusCode())
	}
	return &edge, nil
}

func (c *Client) ExportSpace(spaceID, format string) (string, error) {
	resp, err := c.client.R().
		SetQueryParam("format", format).
		Get("/spaces/" + spaceID + "/export")
	if err != nil {
		return "", fmt.Errorf("export: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return "", fmt.Errorf("export: status %d", resp.StatusCode())
	}
	return resp.String(), nil
}

type ImportResult struct {
	Imported int `json:"imported"`
	Errors   int `json:"errors"`
}

func (c *Client) ImportSpace(spaceID string, nodes []CreateNodeRequest) (*ImportResult, error) {
	body := map[string]interface{}{
		"nodes": nodes,
		"format": "json",
	}
	var result ImportResult
	resp, err := c.client.R().
		SetBody(body).
		SetResult(&result).
		Post("/spaces/" + spaceID + "/import")
	if err != nil {
		return nil, fmt.Errorf("import: %w", err)
	}
	if resp.StatusCode() != http.StatusOK {
		return nil, fmt.Errorf("import: status %d", resp.StatusCode())
	}
	return &result, nil
}

func MustMarshal(v interface{}) string {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return fmt.Sprintf(`{"error":"marshal: %v"}`, err)
	}
	return string(b)
}

func ParseJSON(s string) map[string]interface{} {
	var result map[string]interface{}
	if err := json.Unmarshal([]byte(s), &result); err != nil {
		return map[string]interface{}{"error": err.Error()}
	}
	return result
}


