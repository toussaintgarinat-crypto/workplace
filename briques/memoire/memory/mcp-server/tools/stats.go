package tools

import (
	"context"
	"fmt"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/garinat/memory-mcp/client"
)

func Stats(cl *client.Client) server.Tool {
	return server.NewTool(
		server.Tool{
			Tool: mcp.NewTool("memory_stats",
				mcp.Description("Statistiques sur la mémoire (taille, répartition IPCRa, tiers)"),
				requiredString("space_id", "ID de l'espace"),
			),
			Handler: func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				args := req.Params.Arguments
				spaceID := stringArg(args, "space_id")

				stats, err := cl.GetStats(spaceID)
				if err != nil {
					return mcp.NewToolResultText(formatError(err.Error())), nil
				}

				output := fmt.Sprintf("📊 Statistiques Memory\n")
				output += fmt.Sprintf("━━━━━━━━━━━━━━━━━━\n")
				output += fmt.Sprintf("Total nœuds:      %d\n\n", stats.TotalNodes)

				output += "Par type:\n"
				for t, c := range stats.ByType {
					output += fmt.Sprintf("  %s: %d\n", t, c)
				}

				output += "\nPar stage IPCRa:\n"
				for s, c := range stats.ByStage {
					output += fmt.Sprintf("  %s: %d\n", s, c)
				}

				output += "\nPar tier:\n"
				for t, c := range stats.ByTier {
					output += fmt.Sprintf("  %s: %d\n", t, c)
				}

				return mcp.NewToolResultText(output), nil
			},
		},
	)
}
