package tools

import (
	"context"
	"fmt"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/garinat/memory-mcp/client"
)

func Search(cl *client.Client) server.Tool {
	return server.NewTool(
		server.Tool{
			Tool: mcp.NewTool("memory_search",
				mcp.Description("Recherche textuelle + vectorielle combinée"),
				requiredString("space_id", "ID de l'espace"),
				requiredString("query", "Requête de recherche"),
				optionalString("type", "Filtre par type"),
				optionalString("limit", "Nombre max de résultats (défaut: 20)"),
			),
			Handler: func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				args := req.Params.Arguments
				spaceID := stringArg(args, "space_id")

				results, err := cl.Search(
					spaceID,
					stringArg(args, "query"),
					intArg(args, "limit", 20),
					stringArg(args, "type"),
				)
				if err != nil {
					return mcp.NewToolResultText(formatError(err.Error())), nil
				}

				output := fmt.Sprintf("Recherche: %s\n", stringArg(args, "query"))
				output += fmt.Sprintf("Résultats: %d\n\n", len(results))
				for i, r := range results {
					output += fmt.Sprintf("%d. [%.2f] %s (%s)\n", i+1, r.Score, r.Title, r.Type)
				}

				return mcp.NewToolResultText(output), nil
			},
		},
	)
}
