package tools

import (
	"context"
	"fmt"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/garinat/memory-mcp/client"
)

func Insights(cl *client.Client) server.Tool {
	return server.NewTool(
		server.Tool{
			Tool: mcp.NewTool("memory_get_insights",
				mcp.Description("État global : top souvenirs, vieillissants, suggestions en attente"),
				requiredString("space_id", "ID de l'espace"),
			),
			Handler: func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				args := req.Params.Arguments
				spaceID := stringArg(args, "space_id")

				info, err := cl.GetSpaceInfo(spaceID)
				if err != nil {
					return mcp.NewToolResultText(formatError(err.Error())), nil
				}

				output := fmt.Sprintf("📊 Espace: %s\n", info.Space.Name)
				output += fmt.Sprintf("   Description: %s\n\n", info.Space.Description)
				output += fmt.Sprintf("📦 Total souvenirs: %d\n", info.TotalNodes)

				output += "\n📁 Par type:\n"
				for t, c := range info.ByType {
					output += fmt.Sprintf("   %s: %d\n", t, c)
				}

				output += "\n📁 Par stage:\n"
				for s, c := range info.ByStage {
					output += fmt.Sprintf("   %s: %d\n", s, c)
				}

				output += "\n📁 Par tier:\n"
				for t, c := range info.ByTier {
					output += fmt.Sprintf("   %s: %d\n", t, c)
				}

				output += fmt.Sprintf("\n⚠️  Vieillissants: %d\n", len(info.Aging))
				for _, n := range info.Aging {
					output += fmt.Sprintf("   • %s (%s)\n", n.Title, n.StorageTier)
				}

				output += fmt.Sprintf("\n💡 Suggestions en attente: %d\n", len(info.Suggestions))
				for _, s := range info.Suggestions {
					output += fmt.Sprintf("   • [%s] %s\n", s.Status, s.Action)
				}

				return mcp.NewToolResultText(output), nil
			},
		},
	)
}
