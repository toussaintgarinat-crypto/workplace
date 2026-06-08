package tools

import (
	"context"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/garinat/memory-mcp/client"
)

func UpdateStage(cl *client.Client) server.Tool {
	return server.NewTool(
		server.Tool{
			Tool: mcp.NewTool("memory_update_stage",
				mcp.Description("Change l'étape IPCRa d'un souvenir"),
				requiredString("space_id", "ID de l'espace"),
				requiredString("node_id", "ID du nœud"),
				mcp.WithString("stage",
					mcp.Required(),
					mcp.Description("Nouveau stage"),
					mcp.Enum("input", "projet", "casquette", "ressource", "archive"),
				),
				optionalString("reason", "Raison du changement"),
			),
			Handler: func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				args := req.Params.Arguments
				node, err := cl.UpdateStage(
					stringArg(args, "space_id"),
					stringArg(args, "node_id"),
					stringArg(args, "stage"),
					stringArg(args, "reason"),
				)
				if err != nil {
					return mcp.NewToolResultText(formatError(err.Error())), nil
				}
				return mcp.NewToolResultText(formatResult(node)), nil
			},
		},
	)
}
