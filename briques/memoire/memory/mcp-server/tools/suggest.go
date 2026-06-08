package tools

import (
	"context"
	"fmt"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/garinat/memory-mcp/client"
)

func Suggest(cl *client.Client) server.Tool {
	return server.NewTool(
		server.Tool{
			Tool: mcp.NewTool("memory_suggest_transitions",
				mcp.Description("Demande au LLM de suggérer les prochaines étapes IPCRa"),
				requiredString("space_id", "ID de l'espace"),
				optionalString("node_id", "ID du nœud (optionnel — si vide, suggère pour tous les inputs)"),
			),
			Handler: func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				args := req.Params.Arguments
				spaceID := stringArg(args, "space_id")

				result, err := cl.RunGardien(spaceID)
				if err != nil {
					return mcp.NewToolResultText(formatError(err.Error())), nil
				}

				output := "Suggestions du gardien:\n\n"
				if details, ok := result["results"]; ok {
					output += fmt.Sprintf("%v", details)
				} else {
					output += "Aucune suggestion pour le moment."
				}

				return mcp.NewToolResultText(output), nil
			},
		},
	)
}
