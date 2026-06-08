package main

import (
	"fmt"
	"log"
	"os"

	"github.com/mark3labs/mcp-go/server"

	"github.com/garinat/memory-mcp/client"
	"github.com/garinat/memory-mcp/tools"
)

func main() {
	backendURL := os.Getenv("MEMORY_BACKEND_URL")
	if backendURL == "" {
		backendURL = "http://localhost:8000"
	}

	token := os.Getenv("MEMORY_TOKEN")
	if token == "" {
		log.Fatal("MEMORY_TOKEN environment variable is required")
	}

	port := os.Getenv("MCP_PORT")
	if port == "" {
		port = "8100"
	}

	cl := client.New(backendURL, token)

	srv := server.NewMCPServer(
		"Memory MCP Server",
		"0.1.0",
		server.WithResourceCapabilities(false, false),
		server.WithPromptCapabilities(false),
		server.WithLogging(),
	)

	srv.AddTool(tools.Remember(cl))
	srv.AddTool(tools.Recall(cl))
	srv.AddTool(tools.Search(cl))
	srv.AddTool(tools.GraphQuery(cl))
	srv.AddTool(tools.UpdateStage(cl))
	srv.AddTool(tools.Suggest(cl))
	srv.AddTool(tools.Insights(cl))
	srv.AddTool(tools.Stats(cl))

	addr := fmt.Sprintf(":%s", port)
	log.Printf("Memory MCP Server listening on %s", addr)
	log.Printf("Backend URL: %s", backendURL)

	if err := server.ServeStdio(srv); err != nil {
		log.Fatalf("Server error: %v", err)
	}
}
