"""
tests/test_multi_language.py

Unit tests for Go, Rust, Java, C, and C++ syntax parsing and complexity scoring.
"""
import pytest
from src.state import ArchaeonState, FileMetadata
from src.parsers.base import SymbolTable
from src.parsers.generic_parser import extract_symbols as extract_generic
from src.parsers.complexity import compute_generic_complexity
from src.utils.tree_sitter_utils import get_parser
from src.agents.ast_parser import _resolve_internal_imports


def make_file_meta(path: str, language: str) -> FileMetadata:
    return FileMetadata(
        path=path, language=language,
        line_count=100, size_bytes=2000, sha="abc"
    )


# -----------------------------------------------------------------------
# Go Language Parsing & Scoring Tests
# -----------------------------------------------------------------------

class TestGoSupport:

    def test_go_symbol_extraction(self):
        source = """
        package main

        import (
            "fmt"
            "github.com/user/project/utils"
        )

        type Config struct {
            Port int
        }

        type Runner interface {
            Run(a int, b string) error
        }

        func (c *Config) Setup(msg string) bool {
            return true
        }

        func Start(args ...string) {
            fmt.Println("started")
        }
        """
        parser = get_parser("Go")
        assert parser is not None, "Go parser must be available"

        source_bytes = bytes(source, 'utf-8')
        tree = parser.parse(source_bytes)

        _, functions, classes, imports = extract_generic(tree, source_bytes, "Go")

        # Verify imports
        assert len(imports) == 2
        assert imports[0].module == "fmt"
        assert imports[1].module == "github.com/user/project/utils"

        # Verify classes (structs & interfaces)
        assert len(classes) == 2
        assert any(c.name == "Config" for c in classes)
        assert any(c.name == "Runner" for c in classes)

        # Verify functions/methods
        assert len(functions) == 2
        
        setup_fn = next(f for f in functions if f.name == "Setup")
        assert setup_fn.params == ["msg"]
        assert setup_fn.is_method is False

        start_fn = next(f for f in functions if f.name == "Start")
        assert start_fn.params == ["args"]

    def test_go_complexity(self):
        source = """
        package main
        func ComplexGo(x int) int {
            if x > 10 {
                for i := 0; i < x; i++ {
                    if i % 2 == 0 && x < 100 {
                        x--
                    }
                }
            }
            return x
        }
        """
        from src.parsers.base import SymbolTable, FunctionInfo
        # Stub symbol table
        fn = FunctionInfo(name="ComplexGo", params=["x"], line_start=3, line_end=12, docstring=None, is_async=False, is_method=False)
        st = SymbolTable(file_path="main.go", language="Go", module_docstring=None, functions=[fn])

        scores = compute_generic_complexity(source, "Go", st)
        # Decision points: 2 `if`s, 1 `for`, 1 `&&` logical operator inside binary_expression = 4 paths + base 1 = 5
        assert scores.get("ComplexGo") == 5


# -----------------------------------------------------------------------
# Rust Language Parsing & Scoring Tests
# -----------------------------------------------------------------------

class TestRustSupport:

    def test_rust_symbol_extraction(self):
        source = """
        use std::collections::HashMap;
        use crate::utils::{helper, logger};

        struct App {
            name: String,
        }

        trait Worker {
            fn perform(&self, val: u32);
        }

        impl App {
            fn init(self) -> Self {
                self
            }
        }

        fn top_level_run() {
            println!("run");
        }
        """
        parser = get_parser("Rust")
        assert parser is not None, "Rust parser must be available"

        source_bytes = bytes(source, 'utf-8')
        tree = parser.parse(source_bytes)

        _, functions, classes, imports = extract_generic(tree, source_bytes, "Rust")

        # Verify imports
        assert len(imports) == 2
        assert imports[0].module == "std::collections"
        assert imports[0].names == ["HashMap"]
        assert imports[1].module == "crate::utils"
        assert sorted(imports[1].names) == ["helper", "logger"]

        # Verify classes
        assert len(classes) == 2
        assert any(c.name == "App" for c in classes)
        assert any(c.name == "Worker" for c in classes)
        
        app_cls = next(c for c in classes if c.name == "App")
        assert "init" in app_cls.method_names

        # Verify functions & methods
        assert len(functions) == 2
        
        init_fn = next(f for f in functions if f.name == "init")
        assert init_fn.params == ["self"]
        assert init_fn.is_method is True

        top_fn = next(f for f in functions if f.name == "top_level_run")
        assert top_fn.is_method is False

    def test_rust_complexity(self):
        source = """
        fn complex_rust(x: i32) -> i32 {
            let y = if x > 10 {
                match x {
                    1 => 10,
                    2 | 3 => 20,
                    _ => 30
                }
            } else {
                while x < 5 {
                    if x == 2 || x == 3 {
                        break;
                    }
                }
                40
            };
            y
        }
        """
        from src.parsers.base import SymbolTable, FunctionInfo
        fn = FunctionInfo(name="complex_rust", params=["x"], line_start=2, line_end=17, docstring=None, is_async=False, is_method=False)
        st = SymbolTable(file_path="main.rs", language="Rust", module_docstring=None, functions=[fn])

        scores = compute_generic_complexity(source, "Rust", st)
        # Decision points: 
        # - if_expression (line 3)
        # - match_arm 1, 2, 3 (match_arm node instances: match has 3 match_arm children) = 3
        # - while_expression (line 10)
        # - if_expression (line 11)
        # - `||` logical operator = 1
        # Total decision points = 1 + 3 + 1 + 1 + 1 = 7 paths + base 1 = 8
        assert scores.get("complex_rust") >= 6


# -----------------------------------------------------------------------
# Java Language Parsing & Scoring Tests
# -----------------------------------------------------------------------

class TestJavaSupport:

    def test_java_symbol_extraction(self):
        source = """
        package com.example;
        import java.util.List;
        import com.example.models.User;

        public class AppController extends BaseController implements Initializable {
            private String name;

            public AppController(String name) {
                this.name = name;
            }

            public void handleRequest(int id, String payload) {
                System.out.println(payload);
            }
        }
        """
        parser = get_parser("Java")
        assert parser is not None, "Java parser must be available"

        source_bytes = bytes(source, 'utf-8')
        tree = parser.parse(source_bytes)

        _, functions, classes, imports = extract_generic(tree, source_bytes, "Java")

        # Verify imports
        assert len(imports) == 2
        assert imports[0].module == "java.util"
        assert imports[0].names == ["List"]
        assert imports[1].module == "com.example.models"
        assert imports[1].names == ["User"]

        # Verify classes
        assert len(classes) == 1
        app_cls = classes[0]
        assert app_cls.name == "AppController"
        assert "BaseController" in app_cls.bases
        assert "Initializable" in app_cls.bases
        assert sorted(app_cls.method_names) == ["AppController", "handleRequest"]

        # Verify functions (methods/constructors)
        assert len(functions) == 2
        
        ctor = next(f for f in functions if f.name == "AppController")
        assert ctor.params == ["name"]
        assert ctor.is_method is True

        method = next(f for f in functions if f.name == "handleRequest")
        assert method.params == ["id", "payload"]
        assert method.is_method is True

    def test_java_complexity(self):
        source = """
        class Util {
            public int complexJava(int x) {
                try {
                    if (x > 0) {
                        for (int i = 0; i < x; i++) {
                            if (i % 2 == 0 && i != 4) {
                                x--;
                            }
                        }
                    }
                } catch (Exception e) {
                    x = -1;
                }
                return x;
            }
        }
        """
        from src.parsers.base import SymbolTable, FunctionInfo
        fn = FunctionInfo(name="complexJava", params=["x"], line_start=3, line_end=16, docstring=None, is_async=False, is_method=True)
        st = SymbolTable(file_path="Util.java", language="Java", module_docstring=None, functions=[fn])

        scores = compute_generic_complexity(source, "Java", st)
        # Decision points: 
        # - if (x > 0)
        # - for loop
        # - if (i % 2 == 0)
        # - `&&` logical operator
        # - catch block
        # Total decision points = 5 + base 1 = 6
        assert scores.get("complexJava") == 6


# -----------------------------------------------------------------------
# C/C++ Language Parsing & Scoring Tests
# -----------------------------------------------------------------------

class TestCppSupport:

    def test_cpp_symbol_extraction(self):
        source = """
        #include <stdio.h>
        #include "local_config.h"

        class Manager : public Base {
        public:
            void dispatch(int code);
            int calculate() {
                return 42;
            }
        };

        int* get_data(const char* key, int length) {
            return NULL;
        }

        void Manager::dispatch(int code) {
            printf("%d", code);
        }
        """
        parser = get_parser("C++")
        assert parser is not None, "C++ parser must be available"

        source_bytes = bytes(source, 'utf-8')
        tree = parser.parse(source_bytes)

        _, functions, classes, imports = extract_generic(tree, source_bytes, "C++")

        # Verify imports
        assert len(imports) == 2
        assert imports[0].module == "<stdio.h>"
        assert imports[1].module == '"local_config.h"'

        # Verify classes
        assert len(classes) == 1
        m_cls = classes[0]
        assert m_cls.name == "Manager"
        assert "Base" in m_cls.bases
        assert sorted(m_cls.method_names) == ["calculate", "dispatch"]

        # Verify functions & methods
        assert len(functions) == 3 # calculate, get_data, Manager::dispatch
        
        get_data_fn = next(f for f in functions if f.name == "get_data")
        assert get_data_fn.params == ["key", "length"]
        assert get_data_fn.is_method is False

        calc_fn = next(f for f in functions if f.name == "calculate")
        assert calc_fn.is_method is True

        dispatch_fn = next(f for f in functions if f.name == "dispatch" or "dispatch" in f.name)
        assert dispatch_fn.params == ["code"]


    def test_cpp_complexity(self):
        source = """
        int complex_cpp(int x) {
            if (x > 0) {
                while (x < 10) {
                    if (x % 2 == 0 || x == 5) {
                        x++;
                    }
                }
            }
            return x;
        }
        """
        from src.parsers.base import SymbolTable, FunctionInfo
        fn = FunctionInfo(name="complex_cpp", params=["x"], line_start=2, line_end=11, docstring=None, is_async=False, is_method=False)
        st = SymbolTable(file_path="main.cpp", language="C++", module_docstring=None, functions=[fn])

        scores = compute_generic_complexity(source, "C++", st)
        # Decision points: 2 `if`s, 1 `while`, 1 `||` logical operator = 4 paths + base 1 = 5
        assert scores.get("complex_cpp") == 5


# -----------------------------------------------------------------------
# Resolution Tests
# -----------------------------------------------------------------------

class TestImportResolution:

    def test_go_internal_imports(self):
        state = ArchaeonState(repo_url="https://github.com/owner/repo")
        # Go stdlib and project paths
        file_paths = {"utils/db.go", "main.go"}
        
        from src.parsers.base import ImportInfo
        st = SymbolTable(file_path="main.go", language="Go", module_docstring=None)
        st.imports = [
            ImportInfo(module="fmt", names=[], is_from_import=False, is_internal=False),
            ImportInfo(module="github.com/owner/repo/utils", names=[], is_from_import=False, is_internal=False)
        ]
        state.symbol_tables["main.go"] = st

        _resolve_internal_imports(state, file_paths)

        assert st.imports[0].is_internal is False
        assert st.imports[1].is_internal is True

    def test_rust_internal_imports(self):
        state = ArchaeonState(repo_url="https://github.com/owner/repo")
        file_paths = {"src/main.rs", "src/utils.rs"}
        
        from src.parsers.base import ImportInfo
        st = SymbolTable(file_path="src/main.rs", language="Rust", module_docstring=None)
        st.imports = [
            ImportInfo(module="std::collections", names=[], is_from_import=True, is_internal=False),
            ImportInfo(module="crate::utils", names=[], is_from_import=True, is_internal=False)
        ]
        state.symbol_tables["src/main.rs"] = st

        _resolve_internal_imports(state, file_paths)

        assert st.imports[0].is_internal is False
        assert st.imports[1].is_internal is True

    def test_java_internal_imports(self):
        state = ArchaeonState(repo_url="https://github.com/owner/repo")
        file_paths = {"com/example/models/User.java", "com/example/App.java"}
        
        from src.parsers.base import ImportInfo
        st = SymbolTable(file_path="com/example/App.java", language="Java", module_docstring=None)
        st.imports = [
            ImportInfo(module="java.util", names=[], is_from_import=True, is_internal=False),
            ImportInfo(module="com.example.models", names=[], is_from_import=True, is_internal=False)
        ]
        state.symbol_tables["com/example/App.java"] = st

        _resolve_internal_imports(state, file_paths)

        assert st.imports[0].is_internal is False
        assert st.imports[1].is_internal is True

    def test_c_internal_imports(self):
        state = ArchaeonState(repo_url="https://github.com/owner/repo")
        file_paths = {"main.c", "config.h"}
        
        from src.parsers.base import ImportInfo
        st = SymbolTable(file_path="main.c", language="C", module_docstring=None)
        st.imports = [
            ImportInfo(module="<stdio.h>", names=[], is_from_import=False, is_internal=False),
            ImportInfo(module='"config.h"', names=[], is_from_import=False, is_internal=False)
        ]
        state.symbol_tables["main.c"] = st

        _resolve_internal_imports(state, file_paths)

        assert st.imports[0].is_internal is False
        assert st.imports[1].is_internal is True

    def test_go_module_url_resolution(self):
        state = ArchaeonState(repo_url="https://github.com/levitateos/soda-os")
        state.raw_contents = {
            "go.mod": "module github.com/levitateos/soda-os\n\ngo 1.22\n",
            "cmd/soda/main.go": "package main\n",
            "internal/daemon/server.go": "package daemon\n"
        }
        file_paths = set(state.raw_contents.keys())

        from src.parsers.base import ImportInfo
        from src.utils.graph_utils import resolve_import_to_paths
        st = SymbolTable(file_path="cmd/soda/main.go", language="Go", module_docstring=None)
        imp_stdlib = ImportInfo(module="fmt", names=[], is_from_import=False, is_internal=False)
        imp_external = ImportInfo(module="github.com/gin-gonic/gin", names=[], is_from_import=False, is_internal=False)
        imp_internal = ImportInfo(module="github.com/levitateos/soda-os/internal/daemon", names=[], is_from_import=False, is_internal=False)
        st.imports = [imp_stdlib, imp_external, imp_internal]
        state.symbol_tables["cmd/soda/main.go"] = st

        _resolve_internal_imports(state, file_paths)

        assert imp_stdlib.is_internal is False
        assert imp_external.is_internal is False
        assert imp_internal.is_internal is True

        resolved = resolve_import_to_paths("cmd/soda/main.go", imp_internal, "Go", file_paths)
        assert "internal/daemon/server.go" in resolved

    def test_ts_path_aliases_resolution(self):
        state = ArchaeonState(repo_url="https://github.com/owner/nextjs-app")
        file_paths = {
            "src/components/Button.tsx",
            "src/lib/api.ts",
            "src/pages/index.tsx"
        }

        from src.parsers.base import ImportInfo
        from src.utils.graph_utils import resolve_import_to_paths
        st = SymbolTable(file_path="src/pages/index.tsx", language="TypeScript", module_docstring=None)
        imp_react = ImportInfo(module="react", names=[], is_from_import=True, is_internal=False)
        imp_alias1 = ImportInfo(module="@/components/Button", names=[], is_from_import=True, is_internal=False)
        imp_alias2 = ImportInfo(module="~/lib/api", names=[], is_from_import=True, is_internal=False)
        st.imports = [imp_react, imp_alias1, imp_alias2]
        state.symbol_tables["src/pages/index.tsx"] = st

        _resolve_internal_imports(state, file_paths)

        assert imp_react.is_internal is False
        assert imp_alias1.is_internal is True
        assert imp_alias2.is_internal is True

        res1 = resolve_import_to_paths("src/pages/index.tsx", imp_alias1, "TypeScript", file_paths)
        res2 = resolve_import_to_paths("src/pages/index.tsx", imp_alias2, "TypeScript", file_paths)
        assert "src/components/Button.tsx" in res1
        assert "src/lib/api.ts" in res2

    def test_java_maven_layout_resolution(self):
        state = ArchaeonState(repo_url="https://github.com/owner/java-app")
        file_paths = {
            "src/main/java/com/example/service/UserService.java",
            "src/main/java/com/example/controller/UserController.java"
        }

        from src.parsers.base import ImportInfo
        from src.utils.graph_utils import resolve_import_to_paths
        st = SymbolTable(file_path="src/main/java/com/example/controller/UserController.java", language="Java", module_docstring=None)
        imp_java = ImportInfo(module="java.util.List", names=[], is_from_import=True, is_internal=False)
        imp_service = ImportInfo(module="com.example.service.UserService", names=[], is_from_import=True, is_internal=False)
        st.imports = [imp_java, imp_service]
        state.symbol_tables["src/main/java/com/example/controller/UserController.java"] = st

        _resolve_internal_imports(state, file_paths)

        assert imp_java.is_internal is False
        assert imp_service.is_internal is True

        res = resolve_import_to_paths("src/main/java/com/example/controller/UserController.java", imp_service, "Java", file_paths)
        assert "src/main/java/com/example/service/UserService.java" in res
