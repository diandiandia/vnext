// This program parses supplied bytes only. It never loads target packages.
package main

import (
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"os"
	"sort"
	"strconv"
)

type sourceFile struct {
	Path   string `json:"path"`
	Source []byte `json:"source"`
}

type request struct {
	Files []sourceFile `json:"files"`
	Limit int          `json:"limit"`
}

type candidate struct {
	Path   string `json:"path"`
	Line   int    `json:"line"`
	Column int    `json:"column"`
	API    string `json:"api"`
}

type result struct {
	Path       string      `json:"path"`
	Error      string      `json:"error,omitempty"`
	Count      int         `json:"count"`
	Candidates []candidate `json:"candidates"`
}

var apis = map[string]bool{
	"os/exec.Command": true, "os/exec.CommandContext": true,
	"io.ReadAll": true, "io/ioutil.ReadAll": true,
	"path.Join": true, "path.Clean": true,
	"path/filepath.Join": true, "path/filepath.Clean": true,
	"path/filepath.Abs": true, "path/filepath.Rel": true,
}

func scan(file sourceFile, limit int) result {
	out := result{Path: file.Path, Candidates: []candidate{}}
	positions := token.NewFileSet()
	tree, err := parser.ParseFile(positions, file.Path, file.Source, parser.AllErrors)
	if err != nil {
		// Parser errors can contain attacker-controlled tokens and paths.
		out.Error = "invalid Go syntax"
		return out
	}
	imports := map[string]string{}
	ambiguous := map[string]bool{}
	for _, spec := range tree.Imports {
		path, err := strconv.Unquote(spec.Path.Value)
		if err != nil {
			out.Error = "invalid Go import"
			return out
		}
		name := path
		for i := len(name) - 1; i >= 0; i-- {
			if name[i] == '/' {
				name = name[i+1:]
				break
			}
		}
		if spec.Name != nil {
			name = spec.Name.Name
		}
		if name == "." || name == "_" {
			continue
		}
		if _, exists := imports[name]; exists {
			ambiguous[name] = true
		}
		imports[name] = path
	}
	ast.Inspect(tree, func(node ast.Node) bool {
		call, ok := node.(*ast.CallExpr)
		if !ok {
			return true
		}
		selector, ok := call.Fun.(*ast.SelectorExpr)
		if !ok {
			return true
		}
		ident, ok := selector.X.(*ast.Ident)
		// The parser's object resolver binds lexical declarations, but leaves
		// imported package references unresolved. Do not skip object resolution.
		if !ok || ident.Obj != nil || ambiguous[ident.Name] {
			return true
		}
		path, ok := imports[ident.Name]
		api := path + "." + selector.Sel.Name
		if !ok || !apis[api] {
			return true
		}
		out.Count++
		if len(out.Candidates) < limit {
			position := positions.PositionFor(call.Pos(), false)
			out.Candidates = append(out.Candidates, candidate{
				Path: file.Path, Line: position.Line, Column: position.Column, API: api,
			})
		}
		return true
	})
	return out
}

func main() {
	var input request
	if err := json.NewDecoder(io.LimitReader(os.Stdin, 8*1024*1024)).Decode(&input); err != nil ||
		len(input.Files) > 128 || input.Limit < 1 || input.Limit > 200 {
		fmt.Fprintln(os.Stderr, "invalid bounded parser request")
		os.Exit(2)
	}
	total := 0
	for _, file := range input.Files {
		total += len(file.Source)
		if len(file.Source) > 1024*1024 || total > 4*1024*1024 || len(file.Path) > 4096 {
			fmt.Fprintln(os.Stderr, "parser input limit exceeded")
			os.Exit(2)
		}
	}
	sort.Slice(input.Files, func(i, j int) bool { return input.Files[i].Path < input.Files[j].Path })
	results := make([]result, 0, len(input.Files))
	remaining := input.Limit
	for _, file := range input.Files {
		out := scan(file, remaining)
		remaining -= len(out.Candidates)
		results = append(results, out)
	}
	if err := json.NewEncoder(os.Stdout).Encode(results); err != nil {
		os.Exit(2)
	}
}
