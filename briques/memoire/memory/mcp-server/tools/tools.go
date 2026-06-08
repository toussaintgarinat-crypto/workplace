package tools

import (
	"fmt"

	"github.com/mark3labs/mcp-go/mcp"

	"github.com/garinat/memory-mcp/client"
)

func stringArg(args map[string]interface{}, key string) string {
	v, ok := args[key]
	if !ok {
		return ""
	}
	s, _ := v.(string)
	return s
}

func intArg(args map[string]interface{}, key string, defaultVal int) int {
	v, ok := args[key]
	if !ok {
		return defaultVal
	}
	f, _ := v.(float64)
	return int(f)
}

func requiredString(name, desc string) mcp.ToolOption {
	return mcp.WithString(name, mcp.Required(), mcp.Description(desc))
}

func optionalString(name, desc string) mcp.ToolOption {
	return mcp.WithString(name, mcp.Description(desc))
}

func optionalInt(name, desc string, defaultVal int) mcp.ToolOption {
	return mcp.WithNumber(name, mcp.Description(desc), mcp.DefaultNumber(float64(defaultVal)))
}

func formatResult(data interface{}) string {
	return client.MustMarshal(data)
}

func formatError(msg string) string {
	return fmt.Sprintf(`{"error":"%s"}`, msg)
}
