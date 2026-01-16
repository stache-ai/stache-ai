"""Tests for OllamaLLMProvider.generate_structured()"""

import pytest
import httpx
from unittest.mock import Mock, patch
from stache_ai.config import Settings
from stache_ai_ollama.llm import OllamaLLMProvider


@pytest.fixture
def settings():
    """Test settings"""
    return Settings(
        ollama_url="http://localhost:11434",
        ollama_model="llama3.2",
        ollama_llm_timeout=60.0
    )


@pytest.fixture
def provider(settings):
    """Ollama provider instance"""
    return OllamaLLMProvider(settings)


@pytest.fixture
def simple_schema():
    """Simple schema with basic fields"""
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "important": {"type": "boolean", "default": False}
        },
        "required": ["summary"]
    }


@pytest.fixture
def enricher_schema():
    """Schema matching EnterpriseEnricher output"""
    return {
        "type": "object",
        "properties": {
            "concepts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "type": {"type": "string", "enum": ["topic", "skill", "tool", "project"]}
                    }
                }
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"}
            },
            "metadata": {"type": "object", "default": {}}
        },
        "required": ["concepts"]
    }


class TestCapabilities:
    """Test capabilities property"""

    def test_has_structured_output_capability(self, provider):
        """Provider should advertise structured_output capability"""
        assert "structured_output" in provider.capabilities
        assert "generate" in provider.capabilities


class TestDirectJSONParsing:
    """Test direct JSON parsing (happy path)"""

    def test_direct_json_response(self, provider, simple_schema):
        """Should parse clean JSON response"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": '{"summary": "Test summary", "key_points": ["Point 1", "Point 2"]}'
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            result = provider.generate_structured("Summarize this", simple_schema)

        assert result["summary"] == "Test summary"
        assert result["key_points"] == ["Point 1", "Point 2"]
        assert result["important"] is False  # Default applied

    def test_json_with_whitespace(self, provider, simple_schema):
        """Should handle JSON with leading/trailing whitespace"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": '\n\n  {"summary": "Test", "key_points": []}  \n\n'
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            result = provider.generate_structured("Summarize this", simple_schema)

        assert result["summary"] == "Test"
        assert result["key_points"] == []


class TestMarkdownExtraction:
    """Test extraction from markdown code blocks"""

    def test_json_in_markdown_block(self, provider, simple_schema):
        """Should extract JSON from ```json block"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": 'Here is the result:\n```json\n{"summary": "From markdown", "key_points": []}\n```'
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            result = provider.generate_structured("Summarize this", simple_schema)

        assert result["summary"] == "From markdown"

    def test_json_in_plain_code_block(self, provider, simple_schema):
        """Should extract JSON from ``` block without language"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": '```\n{"summary": "Plain block", "key_points": []}\n```'
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            result = provider.generate_structured("Summarize this", simple_schema)

        assert result["summary"] == "Plain block"


class TestNestedJSONExtraction:
    """Test extraction from nested/embedded JSON"""

    def test_json_in_prose(self, provider, simple_schema):
        """Should extract JSON from surrounding prose"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": 'The analysis shows {"summary": "Extracted", "key_points": []} which is interesting.'
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            result = provider.generate_structured("Summarize this", simple_schema)

        assert result["summary"] == "Extracted"

    def test_json_with_nested_objects(self, provider, enricher_schema):
        """Should handle nested objects in arrays"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": '{"concepts": [{"text": "Python", "type": "skill"}], "entities": ["NASA"]}'
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            result = provider.generate_structured("Extract concepts", enricher_schema)

        assert len(result["concepts"]) == 1
        assert result["concepts"][0]["text"] == "Python"
        assert result["concepts"][0]["type"] == "skill"
        assert result["entities"] == ["NASA"]
        assert result["metadata"] == {}  # Default applied


class TestSchemaDefaults:
    """Test schema default application"""

    def test_applies_explicit_defaults(self, provider):
        """Should apply explicit default values"""
        schema = {
            "type": "object",
            "properties": {
                "field1": {"type": "string"},
                "field2": {"type": "string", "default": "default_value"}
            }
        }

        mock_response = Mock()
        mock_response.json.return_value = {
            "response": '{"field1": "provided"}'
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            result = provider.generate_structured("Test", schema)

        assert result["field1"] == "provided"
        assert result["field2"] == "default_value"

    def test_applies_array_defaults(self, provider, simple_schema):
        """Should default missing arrays to []"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": '{"summary": "Only summary"}'
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            result = provider.generate_structured("Test", simple_schema)

        assert result["key_points"] == []

    def test_applies_boolean_defaults(self, provider):
        """Should default missing booleans to False"""
        schema = {
            "type": "object",
            "properties": {
                "flag": {"type": "boolean"}
            }
        }

        mock_response = Mock()
        mock_response.json.return_value = {
            "response": '{}'
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            result = provider.generate_structured("Test", schema)

        assert result["flag"] is False


class TestSchemaPromptBuilding:
    """Test schema prompt generation"""

    def test_basic_field_descriptions(self, provider):
        """Should build field descriptions for basic types"""
        schema = {
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"}
            },
            "required": ["name"]
        }

        prompt = provider._build_schema_prompt(schema)

        assert '"name": string (required)' in prompt
        assert '"count": integer (optional)' in prompt
        assert "Output ONLY valid JSON" in prompt

    def test_array_field_descriptions(self, provider):
        """Should describe array types correctly"""
        schema = {
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}, "value": {"type": "number"}}
                    }
                }
            }
        }

        prompt = provider._build_schema_prompt(schema)

        assert 'array of string' in prompt
        assert 'array of objects with fields [id, value]' in prompt

    def test_enum_field_descriptions(self, provider):
        """Should describe enum constraints"""
        schema = {
            "properties": {
                "status": {"type": "string", "enum": ["pending", "active", "done"]}
            }
        }

        prompt = provider._build_schema_prompt(schema)

        assert 'one of ["pending", "active", "done"]' in prompt


class TestHTTPErrorHandling:
    """Test HTTP error handling"""

    def test_timeout_raises_runtime_error(self, provider, simple_schema):
        """Should wrap timeout in RuntimeError"""
        with patch.object(provider.client, 'post', side_effect=httpx.TimeoutException("Timeout")):
            with pytest.raises(RuntimeError) as exc_info:
                provider.generate_structured("Test", simple_schema)

            assert "timed out" in str(exc_info.value).lower()
            assert "60.0s" in str(exc_info.value)

    def test_http_error_raises_runtime_error(self, provider, simple_schema):
        """Should wrap HTTP errors in RuntimeError"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        error = httpx.HTTPStatusError("Error", request=Mock(), response=mock_response)

        with patch.object(provider.client, 'post', side_effect=error):
            with pytest.raises(RuntimeError) as exc_info:
                provider.generate_structured("Test", simple_schema)

            assert "500" in str(exc_info.value)

    def test_invalid_json_raises_value_error(self, provider, simple_schema):
        """Should raise ValueError if JSON cannot be extracted"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": "This is just plain text with no JSON at all"
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            with pytest.raises(ValueError) as exc_info:
                provider.generate_structured("Test", simple_schema)

            assert "Could not extract JSON" in str(exc_info.value)

    def test_ollama_error_in_response_body(self, provider, simple_schema):
        """Should raise RuntimeError if Ollama returns error in response body"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "error": "model not found: nonexistent-model"
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            with pytest.raises(RuntimeError) as exc_info:
                provider.generate_structured("Test", simple_schema)

            assert "Ollama returned error:" in str(exc_info.value)
            assert "model not found" in str(exc_info.value)

    def test_empty_response_raises_value_error(self, provider, simple_schema):
        """Should raise ValueError if Ollama returns empty response"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": ""
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            with pytest.raises(ValueError) as exc_info:
                provider.generate_structured("Test", simple_schema)

            assert "Ollama returned empty response" in str(exc_info.value)


class TestEnricherIntegration:
    """Test integration with enricher schemas"""

    def test_summary_enricher_schema(self, provider):
        """Should work with SummaryEnricher schema"""
        schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "key_points": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["summary"]
        }

        mock_response = Mock()
        mock_response.json.return_value = {
            "response": '{"summary": "Document about Python", "key_points": ["Uses OOP", "Has tests"]}'
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            result = provider.generate_structured("Summarize document", schema)

        assert result["summary"] == "Document about Python"
        assert len(result["key_points"]) == 2

    def test_enterprise_enricher_schema(self, provider, enricher_schema):
        """Should work with EnterpriseEnricher schema"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": '''
            {
                "concepts": [
                    {"text": "Machine Learning", "type": "topic"},
                    {"text": "TensorFlow", "type": "tool"}
                ],
                "entities": ["Google", "Stanford"]
            }
            '''
        }

        with patch.object(provider.client, 'post', return_value=mock_response):
            result = provider.generate_structured("Extract concepts", enricher_schema)

        assert len(result["concepts"]) == 2
        assert result["concepts"][0]["type"] == "topic"
        assert result["entities"] == ["Google", "Stanford"]
        assert result["metadata"] == {}


class TestRequestPayload:
    """Test request payload construction"""

    def test_sends_correct_payload(self, provider, simple_schema):
        """Should send correct request to Ollama API"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": '{"summary": "Test", "key_points": []}'
        }

        with patch.object(provider.client, 'post', return_value=mock_response) as mock_post:
            provider.generate_structured(
                "Test prompt",
                simple_schema,
                max_tokens=1024,
                temperature=0.5
            )

            call_args = mock_post.call_args
            payload = call_args.kwargs['json']

            assert payload["model"] == "llama3.2"
            assert payload["prompt"] == "Test prompt"
            assert payload["format"] == "json"
            assert payload["stream"] is False
            assert payload["options"]["temperature"] == 0.5
            assert payload["options"]["num_predict"] == 1024
            assert "Output ONLY valid JSON" in payload["system"]
