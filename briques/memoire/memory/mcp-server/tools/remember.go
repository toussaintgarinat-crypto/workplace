package tools

import (
	"context"
	"strings"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/garinat/memory-mcp/client"
)

func Remember(cl *client.Client) server.Tool {
	return server.NewTool(
		server.Tool{
			Tool: mcp.NewTool("memory_remember",
				mcp.Description("Stocke un nouveau souvenir dans Memory"),
				requiredString("space_id", "ID de l'espace"),
				requiredString("title", "Titre du souvenir"),
				requiredString("content", "Contenu en Markdown"),
				mcp.WithString("type",
					mcp.Required(),
					mcp.Description("Type du souvenir"),
					mcp.Enum("input", "projet", "casquette", "ressource", "archive"),
				),
				optionalString("source_url", "URL source"),
				optionalString("captured_from", "Origine (web/email/voice/note)"),
				optionalString("tags", "Tags séparés par des virgules"),
				optionalString("location", `JSON: {"wing":"...","room":"...","drawer":"..."}`),
				optionalString("properties", "Propriétés JSON additionnelles (frontmatter)"),
			),
			Handler: func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				args := req.Params.Arguments
				spaceID := stringArg(args, "space_id")
				title := stringArg(args, "title")
				content := stringArg(args, "content")

				frontmatter := make(map[string]interface{})
				if tags := stringArg(args, "tags"); tags != "" {
					tagList := strings.Split(tags, ",")
					tagInterfaces := make([]interface{}, len(tagList))
					for i, t := range tagList {
						tagInterfaces[i] = strings.TrimSpace(t)
					}
					frontmatter["tags"] = tagInterfaces
				}
				if props := stringArg(args, "properties"); props != "" {
					for k, v := range client.ParseJSON(props) {
						frontmatter[k] = v
					}
				}

				loc := stringArg(args, "location")
				var location map[string]string
				if loc != "" {
					parsed := client.ParseJSON(loc)
					location = make(map[string]string)
					for k, v := range parsed {
						if s, ok := v.(string); ok {
							location[k] = s
						}
					}
				}

				reqBody := client.CreateNodeRequest{
					Title:        title,
					ContentMD:    content,
					Type:         stringArg(args, "type"),
					Frontmatter:  frontmatter,
					SourceURL:    stringArg(args, "source_url"),
					CapturedFrom: stringArg(args, "captured_from"),
					Location:     location,
				}

				node, err := cl.CreateNode(spaceID, reqBody)
				if err != nil {
					return mcp.NewToolResultText(formatError(err.Error())), nil
				}
				return mcp.NewToolResultText(formatResult(node)), nil
			},
		},
	)
}
