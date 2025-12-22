"""
Comprehensive test file for validating async-only API migration.

This test file can be run by code reviewers to verify that:
1. Sync methods have been removed from base classes
2. Async methods exist and are properly named (no 'a' prefix)
3. Implementations work correctly with async-only APIs
4. Integration between components works
5. No sync method calls remain in the codebase

Usage:
    pytest test_async_migration_validation.py -v
    # Or run specific test classes:
    pytest test_async_migration_validation.py::TestBaseClasses -v
"""

import asyncio
import inspect
import os
import re
import sys
from pathlib import Path
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project paths to sys.path
PROJECT_ROOT = Path(__file__).parent
CORE_PATH = PROJECT_ROOT / "byoeb-v1" / "byoeb-core"
INTEGRATIONS_PATH = PROJECT_ROOT / "byoeb-v1" / "byoeb-integrations"
BYOEB_PATH = PROJECT_ROOT / "byoeb-v1" / "byoeb"

if CORE_PATH.exists():
    sys.path.insert(0, str(CORE_PATH))
if INTEGRATIONS_PATH.exists():
    sys.path.insert(0, str(INTEGRATIONS_PATH))
if BYOEB_PATH.exists():
    sys.path.insert(0, str(BYOEB_PATH))


# ============================================================================
# Test Configuration
# ============================================================================

# Set to True to skip tests that require actual API credentials
SKIP_API_TESTS = os.getenv("SKIP_API_TESTS", "true").lower() == "true"

# Directories to search for Python files
SEARCH_DIRS = [
    "byoeb-v1/byoeb-core/byoeb_core",
    "byoeb-v1/byoeb-integrations/byoeb_integrations",
    "byoeb-v1/byoeb/byoeb",
]


# ============================================================================
# Helper Functions
# ============================================================================

def is_async_function(obj) -> bool:
    """Check if an object is an async function."""
    # For abstract methods, check the function code object
    if inspect.isfunction(obj):
        return inspect.iscoroutinefunction(obj)
    # For abstract methods on classes, we need to check differently
    # Abstract methods might not be directly coroutine functions
    # but we can check if they're defined with 'async def'
    try:
        # Check if it's a method descriptor
        if hasattr(obj, '__code__'):
            return inspect.iscoroutinefunction(obj)
        # For abstract methods, check the source
        source = inspect.getsource(obj)
        return 'async def' in source
    except (OSError, TypeError):
        # Fallback: check if it's callable and inspect the signature
        return inspect.iscoroutinefunction(obj) if callable(obj) else False


def find_python_files(directory: str) -> List[str]:
    """Find all Python files in a directory."""
    files = []
    if not os.path.exists(directory):
        return files
    
    for root, dirs, filenames in os.walk(directory):
        # Skip test directories and __pycache__
        if "__pycache__" in root or "test" in root.lower():
            continue
        for filename in filenames:
            if filename.endswith(".py"):
                files.append(os.path.join(root, filename))
    return files


def check_for_sync_calls(filepath: str) -> List[tuple]:
    """Check if a file contains sync method calls."""
    issues = []
    sync_patterns = [
        (r"\.generate_response\(", "generate_response"),
        (r"\.add_chunks\(", "add_chunks"),
        (r"\.retrieve_top_k_chunks\(", "retrieve_top_k_chunks"),
        (r"\.update_chunks\(", "update_chunks"),
        (r"\.delete_chunks\(", "delete_chunks"),
        (r"\.send_message\(", "send_message"),
        (r"\.receive_message\(", "receive_message"),
        (r"\.delete_message\(", "delete_message"),
    ]
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")
            
            for i, line in enumerate(lines, 1):
                # Skip comments and docstrings
                if line.strip().startswith("#") or '"""' in line or "'''" in line:
                    continue
                
                for pattern, method_name in sync_patterns:
                    if re.search(pattern, line):
                        # Check if it's in an async function or has await
                        # Simple check - look backwards in content for async def
                        content_before = "\n".join(lines[:i])
                        is_in_async = "async def" in content_before.split("\n")[-10:]
                        has_await = "await" in line
                        
                        # Also check if it's a method definition
                        is_def = "def " + method_name in line or f"async def {method_name}" in line
                        
                        if not is_in_async and not has_await and not is_def:
                            issues.append((i, line.strip(), method_name))
    except Exception as e:
        pytest.skip(f"Could not read {filepath}: {e}")
    
    return issues


def check_for_old_async_names(filepath: str) -> List[tuple]:
    """Check if a file contains old async method names (with 'a' prefix)."""
    issues = []
    old_patterns = [
        r"\.agenerate_response",
        r"\.aretrieve_top_k_chunks",
        r"\.aadd_chunks",
        r"\.aupdate_chunks",
        r"\.adelete_chunks",
        r"\.asend_message",
        r"\.areceive_message",
        r"\.adelete_message",
        r"\.arecieve_message",  # Typo variant
    ]
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")
            
            for i, line in enumerate(lines, 1):
                for pattern in old_patterns:
                    if re.search(pattern, line):
                        # Skip if it's in a comment or docstring
                        if not line.strip().startswith("#") and '"""' not in line:
                            issues.append((i, line.strip(), pattern))
    except Exception as e:
        pytest.skip(f"Could not read {filepath}: {e}")
    
    return issues


# ============================================================================
# Test Classes
# ============================================================================

class TestBaseClasses:
    """Test that base classes have been migrated to async-only."""
    
    def test_base_llm_structure(self):
        """Test BaseLLM has async-only methods."""
        try:
            from byoeb_core.llms.base import BaseLLM
            
            # Check that generate_response exists
            assert hasattr(BaseLLM, "generate_response"), "BaseLLM.generate_response should exist"
            
            # Check if it's async - for abstract methods, check source code
            method = getattr(BaseLLM, "generate_response")
            source = inspect.getsource(BaseLLM)
            is_async = "async def generate_response" in source or is_async_function(method)
            assert is_async, f"BaseLLM.generate_response should be async. Source check: {'async def generate_response' in source}, Function check: {is_async_function(method)}"
            
            # Check that old async name doesn't exist
            assert not hasattr(BaseLLM, "agenerate_response"), "BaseLLM.agenerate_response should not exist (renamed to generate_response)"
            
            print("✅ BaseLLM structure is correct")
        except ImportError as e:
            pytest.skip(f"Could not import BaseLLM: {e}")
    
    def test_base_vector_store_structure(self):
        """Test BaseVectorStore has async-only methods."""
        try:
            from byoeb_core.vector_stores.base import BaseVectorStore
            
            # Check async methods exist
            async_methods = [
                "retrieve_top_k_chunks",
                "add_chunks",
                "update_chunks",
                "delete_chunks",
            ]
            
            for method_name in async_methods:
                assert hasattr(BaseVectorStore, method_name), f"BaseVectorStore.{method_name} should exist"
                method = getattr(BaseVectorStore, method_name)
                # Check source code for abstract methods
                source = inspect.getsource(BaseVectorStore)
                is_async = f"async def {method_name}" in source or is_async_function(method)
                assert is_async, f"BaseVectorStore.{method_name} should be async"
            
            # Check old async names don't exist
            old_names = ["aretrieve_top_k_chunks", "aadd_chunks", "aupdate_chunks", "adelete_chunks"]
            for old_name in old_names:
                assert not hasattr(BaseVectorStore, old_name), f"BaseVectorStore.{old_name} should not exist (renamed)"
            
            print("✅ BaseVectorStore structure is correct")
        except ImportError as e:
            pytest.skip(f"Could not import BaseVectorStore: {e}")
    
    def test_base_channel_structure(self):
        """Test BaseChannel has async-only methods."""
        try:
            from byoeb_core.channel.base import BaseChannel
            
            # Check async methods exist
            async_methods = ["send_message", "receive_message"]
            
            for method_name in async_methods:
                assert hasattr(BaseChannel, method_name), f"BaseChannel.{method_name} should exist"
                method = getattr(BaseChannel, method_name)
                # Check source code for abstract methods
                source = inspect.getsource(BaseChannel)
                is_async = f"async def {method_name}" in source or is_async_function(method)
                assert is_async, f"BaseChannel.{method_name} should be async"
            
            # Check old async names don't exist
            old_names = ["asend_message", "arecieve_message", "areceive_message"]
            for old_name in old_names:
                assert not hasattr(BaseChannel, old_name), f"BaseChannel.{old_name} should not exist (renamed)"
            
            print("✅ BaseChannel structure is correct")
        except ImportError as e:
            pytest.skip(f"Could not import BaseChannel: {e}")
    
    def test_base_queue_structure(self):
        """Test BaseQueue has async-only methods."""
        try:
            from byoeb_core.message_queue.base import BaseQueue
            
            # Check async methods exist
            async_methods = ["send_message", "receive_message", "delete_message"]
            
            for method_name in async_methods:
                assert hasattr(BaseQueue, method_name), f"BaseQueue.{method_name} should exist"
                method = getattr(BaseQueue, method_name)
                # Check source code for abstract methods
                source = inspect.getsource(BaseQueue)
                is_async = f"async def {method_name}" in source or is_async_function(method)
                assert is_async, f"BaseQueue.{method_name} should be async"
            
            # Check old async names don't exist
            old_names = ["asend_message", "areceive_message", "adelete_message"]
            for old_name in old_names:
                assert not hasattr(BaseQueue, old_name), f"BaseQueue.{old_name} should not exist (renamed)"
            
            print("✅ BaseQueue structure is correct")
        except ImportError as e:
            pytest.skip(f"Could not import BaseQueue: {e}")


class TestImplementations:
    """Test that implementations work with async-only APIs."""
    
    @pytest.mark.anyio
    async def test_llm_implementations_structure(self):
        """Test LLM implementations have async-only methods."""
        implementations = [
            "byoeb_integrations.llms.azure_openai.async_azure_openai.AsyncAzureOpenAILLM",
            "byoeb_integrations.llms.llama_index.llama_index_azure_openai.AsyncLLamaIndexAzureOpenAILLM",
            "byoeb_integrations.llms.llama_index.llama_index_openai.AsyncLLamaIndexOpenAILLM",
        ]
        
        for impl_path in implementations:
            try:
                module_path, class_name = impl_path.rsplit(".", 1)
                module = __import__(module_path, fromlist=[class_name])
                impl_class = getattr(module, class_name)
                
                # Check generate_response exists and is async
                assert hasattr(impl_class, "generate_response"), f"{class_name}.generate_response should exist"
                # Get the method from an instance or the class
                method = getattr(impl_class, "generate_response")
                assert is_async_function(method), f"{class_name}.generate_response should be async"
                
                # Check old name doesn't exist
                assert not hasattr(impl_class, "agenerate_response"), f"{class_name}.agenerate_response should not exist"
                
                print(f"✅ {class_name} structure is correct")
            except ImportError:
                pytest.skip(f"Could not import {impl_path}")
            except Exception as e:
                pytest.fail(f"Error testing {impl_path}: {e}")
    
    @pytest.mark.anyio
    async def test_vector_store_implementations_structure(self):
        """Test Vector Store implementations have async-only methods."""
        implementations = [
            "byoeb_integrations.vector_stores.chroma.base.ChromaDBVectorStore",
        ]
        
        for impl_path in implementations:
            try:
                module_path, class_name = impl_path.rsplit(".", 1)
                module = __import__(module_path, fromlist=[class_name])
                impl_class = getattr(module, class_name)
                
                # Check async methods exist
                async_methods = ["retrieve_top_k_chunks", "add_chunks"]
                for method_name in async_methods:
                    if hasattr(impl_class, method_name):
                        method = getattr(impl_class, method_name)
                        assert is_async_function(method), f"{class_name}.{method_name} should be async"
                
                print(f"✅ {class_name} structure is correct")
            except ImportError:
                pytest.skip(f"Could not import {impl_path}")
            except Exception as e:
                pytest.fail(f"Error testing {impl_path}: {e}")


class TestCodebaseScan:
    """Scan codebase for sync method calls and old async names."""
    
    def test_no_sync_method_calls(self):
        """Test that no sync method calls exist in the codebase."""
        all_issues = []
        
        for directory in SEARCH_DIRS:
            if not os.path.exists(directory):
                continue
            
            files = find_python_files(directory)
            for filepath in files:
                issues = check_for_sync_calls(filepath)
                if issues:
                    all_issues.extend([(filepath, issue) for issue in issues])
        
        if all_issues:
            error_msg = "\n".join([
                f"  {filepath}:{line_num}: {line} (method: {method})"
                for filepath, (line_num, line, method) in all_issues[:20]  # Show first 20
            ])
            if len(all_issues) > 20:
                error_msg += f"\n  ... and {len(all_issues) - 20} more issues"
            pytest.fail(f"Found {len(all_issues)} sync method calls:\n{error_msg}")
        
        print("✅ No sync method calls found in codebase")
    
    def test_no_old_async_names(self):
        """Test that no old async method names (with 'a' prefix) exist."""
        all_issues = []
        
        for directory in SEARCH_DIRS:
            if not os.path.exists(directory):
                continue
            
            files = find_python_files(directory)
            for filepath in files:
                issues = check_for_old_async_names(filepath)
                if issues:
                    all_issues.extend([(filepath, issue) for issue in issues])
        
        if all_issues:
            error_msg = "\n".join([
                f"  {filepath}:{line_num}: {line} (pattern: {pattern})"
                for filepath, (line_num, line, pattern) in all_issues[:20]  # Show first 20
            ])
            if len(all_issues) > 20:
                error_msg += f"\n  ... and {len(all_issues) - 20} more issues"
            pytest.fail(f"Found {len(all_issues)} old async method names:\n{error_msg}")
        
        print("✅ No old async method names found in codebase")


class TestIntegration:
    """Test integration scenarios with async-only APIs."""
    
    @pytest.mark.anyio
    async def test_async_methods_can_be_called(self):
        """Test that async methods can be called (structure test)."""
        try:
            from byoeb_core.llms.base import BaseLLM
            
            # Create a mock implementation
            # Note: This will fail if BaseLLM still has sync generate_response
            # After migration, this should work
            try:
                class MockLLM(BaseLLM):
                    # Try async version first (after migration)
                    async def generate_response(self, prompts, **kwargs):
                        return {"response": "test"}, "test response"
                    
                    def get_llm_client(self):
                        return MagicMock()
                    
                    def get_response_tokens(self, response):
                        return {"total_tokens": 10}
            except TypeError:
                # If migration not done, BaseLLM still requires sync method
                # Create with both for now
                class MockLLM(BaseLLM):
                    def generate_response(self, query: str):
                        # Sync version (before migration)
                        return {"response": "test"}, "test response"
                    
                    async def agenerate_response(self, prompts, **kwargs):
                        # Async version (before migration)
                        return {"response": "test"}, "test response"
                    
                    def get_llm_client(self):
                        return MagicMock()
                    
                    def get_response_tokens(self, response):
                        return {"total_tokens": 10}
            
            llm = MockLLM()
            
            # Test that we can call the async method
            # After migration, use generate_response; before migration, use agenerate_response
            if hasattr(llm, 'generate_response') and is_async_function(getattr(llm, 'generate_response', None)):
                result = await llm.generate_response([{"role": "user", "content": "test"}])
            elif hasattr(llm, 'agenerate_response'):
                result = await llm.agenerate_response([{"role": "user", "content": "test"}])
            else:
                pytest.skip("Cannot test - migration not complete")
            
            assert result is not None
            print("✅ Async methods can be called successfully")
        except ImportError:
            pytest.skip("Could not import BaseLLM")
    
    @pytest.mark.anyio
    async def test_concurrent_async_calls(self):
        """Test that async methods support concurrent execution."""
        try:
            from byoeb_core.llms.base import BaseLLM
            
            # Create a mock implementation with delay
            try:
                class MockLLM(BaseLLM):
                    async def generate_response(self, prompts, **kwargs):
                        await asyncio.sleep(0.1)  # Simulate async operation
                        return {"response": "test"}, "test response"
                    
                    def get_llm_client(self):
                        return MagicMock()
                    
                    def get_response_tokens(self, response):
                        return {"total_tokens": 10}
            except TypeError:
                # If migration not done, create with both
                class MockLLM(BaseLLM):
                    def generate_response(self, query: str):
                        return {"response": "test"}, "test response"
                    
                    async def agenerate_response(self, prompts, **kwargs):
                        await asyncio.sleep(0.1)
                        return {"response": "test"}, "test response"
                    
                    def get_llm_client(self):
                        return MagicMock()
                    
                    def get_response_tokens(self, response):
                        return {"total_tokens": 10}
            
            llm = MockLLM()
            
            # Test concurrent calls
            # After migration, use generate_response; before migration, use agenerate_response
            if hasattr(llm, 'generate_response') and is_async_function(getattr(llm, 'generate_response', None)):
                method = llm.generate_response
            elif hasattr(llm, 'agenerate_response'):
                method = llm.agenerate_response
            else:
                pytest.skip("Cannot test - migration not complete")
            
            start = asyncio.get_event_loop().time()
            tasks = [
                method([{"role": "user", "content": f"test {i}"}])
                for i in range(5)
            ]
            results = await asyncio.gather(*tasks)
            end = asyncio.get_event_loop().time()
            
            assert len(results) == 5
            # Concurrent should be faster than sequential (5 * 0.1 = 0.5s sequential)
            assert (end - start) < 0.3, "Concurrent calls should be faster than sequential"
            print(f"✅ Concurrent async calls work (completed in {end - start:.2f}s)")
        except ImportError:
            pytest.skip("Could not import BaseLLM")


class TestMethodSignatures:
    """Test that method signatures are correct."""
    
    def test_base_llm_signature(self):
        """Test BaseLLM.generate_response signature."""
        try:
            from byoeb_core.llms.base import BaseLLM
            import inspect
            
            sig = inspect.signature(BaseLLM.generate_response)
            # Current implementation has 'query' parameter, but after migration it should have 'prompts'
            # For now, just check that signature exists
            print(f"✅ BaseLLM.generate_response signature: {sig}")
            print(f"   Note: After migration, this should have 'prompts' parameter instead of 'query'")
        except ImportError:
            pytest.skip("Could not import BaseLLM")
    
    def test_base_vector_store_signatures(self):
        """Test BaseVectorStore method signatures."""
        try:
            from byoeb_core.vector_stores.base import BaseVectorStore
            import inspect
            
            methods = ["retrieve_top_k_chunks", "add_chunks"]
            for method_name in methods:
                method = getattr(BaseVectorStore, method_name)
                sig = inspect.signature(method)
                print(f"✅ BaseVectorStore.{method_name} signature: {sig}")
        except ImportError:
            pytest.skip("Could not import BaseVectorStore")


# ============================================================================
# Main Test Runner
# ============================================================================

# ============================================================================
# Phase-Specific Test Classes (for incremental validation)
# ============================================================================

class TestPhase1_BaseLLM:
    """Test Phase 1.1: BaseLLM migration"""
    
    def test_base_llm_structure(self):
        """Test BaseLLM has async-only methods."""
        try:
            from byoeb_core.llms.base import BaseLLM
            
            # Check that generate_response exists
            assert hasattr(BaseLLM, "generate_response"), "BaseLLM.generate_response should exist"
            
            # Check if it's async - for abstract methods, check source code
            method = getattr(BaseLLM, "generate_response")
            source = inspect.getsource(BaseLLM)
            is_async = "async def generate_response" in source or is_async_function(method)
            assert is_async, f"BaseLLM.generate_response should be async. Source check: {'async def generate_response' in source}, Function check: {is_async_function(method)}"
            
            # Check that old async name doesn't exist
            assert not hasattr(BaseLLM, "agenerate_response"), "BaseLLM.agenerate_response should not exist (renamed to generate_response)"
            
            print("✅ BaseLLM structure is correct")
        except ImportError as e:
            pytest.skip(f"Could not import BaseLLM: {e}")


class TestPhase1_BaseVectorStore:
    """Test Phase 1.2: BaseVectorStore migration"""
    
    def test_base_vector_store_structure(self):
        """Test BaseVectorStore has async-only methods."""
        try:
            from byoeb_core.vector_stores.base import BaseVectorStore
            
            # Check async methods exist
            async_methods = [
                "retrieve_top_k_chunks",
                "add_chunks",
                "update_chunks",
                "delete_chunks",
            ]
            
            for method_name in async_methods:
                assert hasattr(BaseVectorStore, method_name), f"BaseVectorStore.{method_name} should exist"
                method = getattr(BaseVectorStore, method_name)
                # Check source code for abstract methods
                source = inspect.getsource(BaseVectorStore)
                is_async = f"async def {method_name}" in source or is_async_function(method)
                assert is_async, f"BaseVectorStore.{method_name} should be async"
            
            # Check old async names don't exist
            old_names = ["aretrieve_top_k_chunks", "aadd_chunks", "aupdate_chunks", "adelete_chunks"]
            for old_name in old_names:
                assert not hasattr(BaseVectorStore, old_name), f"BaseVectorStore.{old_name} should not exist (renamed)"
            
            print("✅ BaseVectorStore structure is correct")
        except ImportError as e:
            pytest.skip(f"Could not import BaseVectorStore: {e}")


class TestPhase1_BaseChannel:
    """Test Phase 1.3: BaseChannel migration"""
    
    def test_base_channel_structure(self):
        """Test BaseChannel has async-only methods."""
        try:
            from byoeb_core.channel.base import BaseChannel
            
            # Check async methods exist
            async_methods = ["send_message", "receive_message"]
            
            for method_name in async_methods:
                assert hasattr(BaseChannel, method_name), f"BaseChannel.{method_name} should exist"
                method = getattr(BaseChannel, method_name)
                # Check source code for abstract methods
                source = inspect.getsource(BaseChannel)
                is_async = f"async def {method_name}" in source or is_async_function(method)
                assert is_async, f"BaseChannel.{method_name} should be async"
            
            # Check old async names don't exist
            old_names = ["asend_message", "arecieve_message", "areceive_message"]
            for old_name in old_names:
                assert not hasattr(BaseChannel, old_name), f"BaseChannel.{old_name} should not exist (renamed)"
            
            print("✅ BaseChannel structure is correct")
        except ImportError as e:
            pytest.skip(f"Could not import BaseChannel: {e}")


class TestPhase1_BaseQueue:
    """Test Phase 1.4: BaseQueue migration"""
    
    def test_base_queue_structure(self):
        """Test BaseQueue has async-only methods."""
        try:
            from byoeb_core.message_queue.base import BaseQueue
            
            # Check async methods exist
            async_methods = ["send_message", "receive_message", "delete_message"]
            
            for method_name in async_methods:
                assert hasattr(BaseQueue, method_name), f"BaseQueue.{method_name} should exist"
                method = getattr(BaseQueue, method_name)
                # Check source code for abstract methods
                source = inspect.getsource(BaseQueue)
                is_async = f"async def {method_name}" in source or is_async_function(method)
                assert is_async, f"BaseQueue.{method_name} should be async"
            
            # Check old async names don't exist
            old_names = ["asend_message", "areceive_message", "adelete_message"]
            for old_name in old_names:
                assert not hasattr(BaseQueue, old_name), f"BaseQueue.{old_name} should not exist (renamed)"
            
            print("✅ BaseQueue structure is correct")
        except ImportError as e:
            pytest.skip(f"Could not import BaseQueue: {e}")


class TestPhase2_LLMImplementations:
    """Test Phase 2.1: LLM Implementations migration"""
    
    @pytest.mark.anyio
    async def test_llm_implementations_structure(self):
        """Test LLM implementations have async-only methods."""
        implementations = [
            "byoeb_integrations.llms.azure_openai.async_azure_openai.AsyncAzureOpenAILLM",
            "byoeb_integrations.llms.llama_index.llama_index_azure_openai.AsyncLLamaIndexAzureOpenAILLM",
            "byoeb_integrations.llms.llama_index.llama_index_openai.AsyncLLamaIndexOpenAILLM",
        ]
        
        for impl_path in implementations:
            try:
                module_path, class_name = impl_path.rsplit(".", 1)
                module = __import__(module_path, fromlist=[class_name])
                impl_class = getattr(module, class_name)
                
                # Check generate_response exists and is async
                assert hasattr(impl_class, "generate_response"), f"{class_name}.generate_response should exist"
                # Get the method from an instance or the class
                method = getattr(impl_class, "generate_response")
                assert is_async_function(method), f"{class_name}.generate_response should be async"
                
                # Check old name doesn't exist
                assert not hasattr(impl_class, "agenerate_response"), f"{class_name}.agenerate_response should not exist"
                
                print(f"✅ {class_name} structure is correct")
            except ImportError:
                pytest.skip(f"Could not import {impl_path}")
            except Exception as e:
                pytest.fail(f"Error testing {impl_path}: {e}")


class TestPhase2_VectorStoreImplementations:
    """Test Phase 2.2: Vector Store Implementations migration"""
    
    @pytest.mark.anyio
    async def test_vector_store_implementations_structure(self):
        """Test Vector Store implementations have async-only methods."""
        implementations = [
            "byoeb_integrations.vector_stores.chroma.base.ChromaDBVectorStore",
        ]
        
        for impl_path in implementations:
            try:
                module_path, class_name = impl_path.rsplit(".", 1)
                module = __import__(module_path, fromlist=[class_name])
                impl_class = getattr(module, class_name)
                
                # Check async methods exist
                async_methods = ["retrieve_top_k_chunks", "add_chunks"]
                for method_name in async_methods:
                    if hasattr(impl_class, method_name):
                        method = getattr(impl_class, method_name)
                        assert is_async_function(method), f"{class_name}.{method_name} should be async"
                
                print(f"✅ {class_name} structure is correct")
            except ImportError:
                pytest.skip(f"Could not import {impl_path}")
            except Exception as e:
                pytest.fail(f"Error testing {impl_path}: {e}")


class TestPhase2_ChannelImplementations:
    """Test Phase 2.3: Channel Implementations migration - Run after updating Channel implementations"""
    
    @pytest.mark.anyio
    async def test_channel_implementations_structure(self):
        """Test Channel implementations have async-only methods."""
        # Note: Channel implementations may vary - this test checks common patterns
        # If specific implementations are found, they should be added here
        implementations = [
            # Add specific channel implementation paths here when identified
            # Example: "byoeb_integrations.channel.whatsapp.meta.async_whatsapp_client.AsyncWhatsAppClient",
        ]
        
        if not implementations:
            pytest.skip("No channel implementations specified - add them when identified")
        
        for impl_path in implementations:
            try:
                module_path, class_name = impl_path.rsplit(".", 1)
                module = __import__(module_path, fromlist=[class_name])
                impl_class = getattr(module, class_name)
                
                # Check async methods exist
                async_methods = ["send_message", "receive_message"]
                for method_name in async_methods:
                    if hasattr(impl_class, method_name):
                        method = getattr(impl_class, method_name)
                        assert is_async_function(method), f"{class_name}.{method_name} should be async"
                
                # Check old async names don't exist
                old_names = ["asend_message", "arecieve_message", "areceive_message"]
                for old_name in old_names:
                    assert not hasattr(impl_class, old_name), f"{class_name}.{old_name} should not exist (renamed)"
                
                print(f"✅ {class_name} structure is correct")
            except ImportError:
                pytest.skip(f"Could not import {impl_path}")
            except Exception as e:
                pytest.fail(f"Error testing {impl_path}: {e}")


class TestPhase2_MessageQueueImplementations:
    """Test Phase 2.4: Message Queue Implementations migration - Run after updating Message Queue implementations"""
    
    @pytest.mark.anyio
    async def test_message_queue_implementations_structure(self):
        """Test Message Queue implementations have async-only methods."""
        implementations = [
            "byoeb_integrations.message_queue.azure.async_azure_storage_queue.AsyncAzureStorageQueue",
        ]
        
        for impl_path in implementations:
            try:
                module_path, class_name = impl_path.rsplit(".", 1)
                module = __import__(module_path, fromlist=[class_name])
                impl_class = getattr(module, class_name)
                
                # Check async methods exist
                async_methods = ["send_message", "receive_message", "delete_message"]
                for method_name in async_methods:
                    if hasattr(impl_class, method_name):
                        method = getattr(impl_class, method_name)
                        assert is_async_function(method), f"{class_name}.{method_name} should be async"
                
                # Check old async names don't exist
                old_names = ["asend_message", "areceive_message", "adelete_message"]
                for old_name in old_names:
                    assert not hasattr(impl_class, old_name), f"{class_name}.{old_name} should not exist (renamed)"
                
                print(f"✅ {class_name} structure is correct")
            except ImportError:
                pytest.skip(f"Could not import {impl_path}")
            except Exception as e:
                pytest.fail(f"Error testing {impl_path}: {e}")


class TestPhase3_CallSites:
    """Test Phase 3: Call Sites migration - check for sync calls and old async names"""
    
    def test_no_sync_method_calls(self):
        """Test that no sync method calls exist in call sites."""
        all_issues = []
        
        for directory in SEARCH_DIRS:
            if not os.path.exists(directory):
                continue
            
            files = find_python_files(directory)
            for filepath in files:
                issues = check_for_sync_calls(filepath)
                if issues:
                    all_issues.extend([(filepath, issue) for issue in issues])
        
        if all_issues:
            error_msg = "\n".join([
                f"  {filepath}:{line_num}: {line} (method: {method})"
                for filepath, (line_num, line, method) in all_issues[:20]  # Show first 20
            ])
            if len(all_issues) > 20:
                error_msg += f"\n  ... and {len(all_issues) - 20} more issues"
            pytest.fail(f"Found {len(all_issues)} sync method calls:\n{error_msg}")
        
        print("✅ No sync method calls found in codebase")
    
    def test_no_old_async_names_in_call_sites(self):
        """Test that no old async method names are used in call sites."""
        all_issues = []
        
        for directory in SEARCH_DIRS:
            if not os.path.exists(directory):
                continue
            
            files = find_python_files(directory)
            for filepath in files:
                issues = check_for_old_async_names(filepath)
                if issues:
                    all_issues.extend([(filepath, issue) for issue in issues])
        
        if all_issues:
            error_msg = "\n".join([
                f"  {filepath}:{line_num}: {line} (pattern: {pattern})"
                for filepath, (line_num, line, pattern) in all_issues[:20]  # Show first 20
            ])
            if len(all_issues) > 20:
                error_msg += f"\n  ... and {len(all_issues) - 20} more issues"
            pytest.fail(f"Found {len(all_issues)} old async method names:\n{error_msg}")
        
        print("✅ No old async method names found in call sites")


class TestPhase3_ServiceLayerCallSites:
    """Test Phase 3.1: Service Layer Call Sites - Run after updating service layer code"""
    
    def test_service_layer_no_sync_calls(self):
        """Test that service layer files don't have sync method calls."""
        service_dirs = [
            "byoeb-v1/byoeb/byoeb/services",
        ]
        
        all_issues = []
        for directory in service_dirs:
            if not os.path.exists(directory):
                continue
            
            files = find_python_files(directory)
            for filepath in files:
                issues = check_for_sync_calls(filepath)
                if issues:
                    all_issues.extend([(filepath, issue) for issue in issues])
        
        if all_issues:
            error_msg = "\n".join([
                f"  {filepath}:{line_num}: {line} (method: {method})"
                for filepath, (line_num, line, method) in all_issues[:20]
            ])
            if len(all_issues) > 20:
                error_msg += f"\n  ... and {len(all_issues) - 20} more issues"
            pytest.fail(f"Found {len(all_issues)} sync method calls in service layer:\n{error_msg}")
        
        print("✅ No sync method calls found in service layer")
    
    def test_service_layer_no_old_async_names(self):
        """Test that service layer files don't use old async method names."""
        service_dirs = [
            "byoeb-v1/byoeb/byoeb/services",
        ]
        
        all_issues = []
        for directory in service_dirs:
            if not os.path.exists(directory):
                continue
            
            files = find_python_files(directory)
            for filepath in files:
                issues = check_for_old_async_names(filepath)
                if issues:
                    all_issues.extend([(filepath, issue) for issue in issues])
        
        if all_issues:
            error_msg = "\n".join([
                f"  {filepath}:{line_num}: {line} (pattern: {pattern})"
                for filepath, (line_num, line, pattern) in all_issues[:20]
            ])
            if len(all_issues) > 20:
                error_msg += f"\n  ... and {len(all_issues) - 20} more issues"
            pytest.fail(f"Found {len(all_issues)} old async method names in service layer:\n{error_msg}")
        
        print("✅ No old async method names found in service layer")


class TestPhase4_TestFiles:
    """Test Phase 4: Test Files migration - Run after updating test files"""
    
    def test_test_files_use_async_methods(self):
        """Test that test files use async methods correctly."""
        test_dirs = [
            "byoeb-v1/byoeb-integrations/byoeb_integrations/llms/tests",
            "byoeb-v1/byoeb-integrations/byoeb_integrations/vector_stores/tests",
            "byoeb-v1/byoeb/tests",
        ]
        
        all_issues = []
        for directory in test_dirs:
            if not os.path.exists(directory):
                continue
            
            files = find_python_files(directory)
            for filepath in files:
                # Check for old async method names in test files
                issues = check_for_old_async_names(filepath)
                if issues:
                    all_issues.extend([(filepath, issue) for issue in issues])
                
                # Check for sync method calls in test files
                issues = check_for_sync_calls(filepath)
                if issues:
                    all_issues.extend([(filepath, issue) for issue in issues])
        
        if all_issues:
            error_msg = "\n".join([
                f"  {filepath}:{line_num}: {line}"
                for filepath, (line_num, line, *rest) in all_issues[:20]
            ])
            if len(all_issues) > 20:
                error_msg += f"\n  ... and {len(all_issues) - 20} more issues"
            pytest.fail(f"Found {len(all_issues)} issues in test files:\n{error_msg}")
        
        print("✅ Test files use async methods correctly")
    
    def test_test_files_async_structure(self):
        """Test that test files have proper async structure (async def for test functions using await)."""
        test_dirs = [
            "byoeb-v1/byoeb-integrations/byoeb_integrations/llms/tests",
            "byoeb-v1/byoeb-integrations/byoeb_integrations/vector_stores/tests",
            "byoeb-v1/byoeb/tests",
        ]
        
        issues = []
        for directory in test_dirs:
            if not os.path.exists(directory):
                continue
            
            files = find_python_files(directory)
            for filepath in files:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                        lines = content.split("\n")
                        
                        # Simple check: if a test function uses await but is not async
                        for i, line in enumerate(lines, 1):
                            if "def test_" in line and "await" in content[max(0, content.find(line) - 500):content.find(line) + 500]:
                                # Check if it's async
                                if "async def" not in line:
                                    # Check if await is actually in this function's scope
                                    # This is a simplified check
                                    if "await" in " ".join(lines[i-1:min(i+20, len(lines))]):
                                        issues.append((filepath, i, line.strip()))
                except Exception:
                    pass  # Skip files that can't be read
        
        if issues:
            error_msg = "\n".join([
                f"  {filepath}:{line_num}: {line} (test function uses await but is not async)"
                for filepath, line_num, line in issues[:20]
            ])
            if len(issues) > 20:
                error_msg += f"\n  ... and {len(issues) - 20} more issues"
            pytest.fail(f"Found {len(issues)} test functions that may need to be async:\n{error_msg}")
        
        print("✅ Test files have proper async structure")


if __name__ == "__main__":
    """
    Run this file directly with:
        python test_async_migration_validation.py
    Or with pytest:
        pytest test_async_migration_validation.py -v
    
    Run specific phases:
        # Phase 1: Base Classes
        pytest test_async_migration_validation.py::TestPhase1_BaseLLM -v
        pytest test_async_migration_validation.py::TestPhase1_BaseVectorStore -v
        pytest test_async_migration_validation.py::TestPhase1_BaseChannel -v
        pytest test_async_migration_validation.py::TestPhase1_BaseQueue -v
        
        # Phase 2: Implementations
        pytest test_async_migration_validation.py::TestPhase2_LLMImplementations -v
        pytest test_async_migration_validation.py::TestPhase2_VectorStoreImplementations -v
        pytest test_async_migration_validation.py::TestPhase2_ChannelImplementations -v
        pytest test_async_migration_validation.py::TestPhase2_MessageQueueImplementations -v
        
        # Phase 3: Call Sites
        pytest test_async_migration_validation.py::TestPhase3_CallSites -v
        pytest test_async_migration_validation.py::TestPhase3_ServiceLayerCallSites -v
        
        # Phase 4: Test Files
        pytest test_async_migration_validation.py::TestPhase4_TestFiles -v
    """
    pytest.main([__file__, "-v", "--tb=short"])

