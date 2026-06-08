package tools

import (
	"context"
	"fmt"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/garinat/memory-mcp/client"
)

func GraphQuery(cl *client.Client) server.Tool {
	return server.NewTool(
		server.Tool{
			Tool: mcp.NewTool("memory_graph_query",
				mcp.Description("Explore le graphe autour d'un nœud ou cherche des chemins"),
				requiredString("space_id", "ID de l'espace"),
				mcp.WithString("node_id", mcp.Description("ID du nœud racine pour le sous-graphe")),
				mcp.WithString("from_id", mcp.Description("Nœud de départ pour le chemin")),
				mcp.WithString("to_id", mcp.Description("Nœud d'arrivée pour le chemin")),
				optionalString("depth", "Profondeur de traversée (défaut: 2)"),
				optionalString("direction", "Direction: outgoing/incoming/both (défaut: both)"),
			),
			Handler: func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				args := req.Params.Arguments
				spaceID := stringArg(args, "space_id")
				nodeID := stringArg(args, "node_id")
				fromID := stringArg(args, "from_id")
				toID := stringArg(args, "to_id")

				if fromID != "" && toID != "" {
					path, err := cl.FindPath(spaceID, fromID, toID)
					if err != nil {
						return mcp.NewToolResultText(formatError(err.Error())), nil
					}
					output := fmt.Sprintf("Chemin de %s à %s:\n", fromID, toID)
					for i, n := range path {
						arrow := " → "
						if i == len(path)-1 {
							arrow = ""
						}
						output += fmt.Sprintf("  %s%s%s\n", n.Title, arrow, n.Type)
					}
					return mcp.NewToolResultText(output), nil
				}

				if nodeID != "" {
					graph, err := cl.GetGraph(spaceID, nodeID, intArg(args, "depth", 2))
					if err != nil {
						return mcp.NewToolResultText(formatError(err.Error())), nil
					}
					output := fmt.Sprintf("Graphe autour de %s (profondeur: %d):\n", nodeID, intArg(args, "depth", 2))
					output += fmt.Sprintf("Nœuds: %d, Arêtes: %d\n\n", len(graph.Nodes), len(graph.Edges))
					for _, n := range graph.Nodes {
						output += fmt.Sprintf("  • %s (%s)\n", n.Title, n.Type)
					}
					output += "\nConnexions:\n"
					for _, e := range graph.Edges {
						output += fmt.Sprintf("  %s ─[%s]─→ %s\n", e.SourceID[:8], e.Type, e.TargetID[:8])
					}
					return mcp.NewToolResultText(output), nil
				}

				return mcp.NewToolResultText(formatError("Spécifiez node_id (sous-graphe) ou from_id+to_id (chemin)")), nil
			},
		},
	)
}
