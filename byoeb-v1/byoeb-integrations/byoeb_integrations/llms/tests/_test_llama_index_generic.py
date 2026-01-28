import pytest

# Common test cases shared amongst azure and non-azure LLM variants.
# Your file must define a llm() pytest.fixture. To append test cases
# defined here, import the functions.
#   from _test_llms_generic import *
#   @pytest.fixture
#   def llm_llama():
#       return LLM(...)

@pytest.mark.parametrize(
    "prompts",
    [
        [{}],
        [{"role": "system"}],
        [{"content": "You are a helpful assistant."}],
    ],
)
@pytest.mark.asyncio
async def test_llama_index_openai_prompt_format(llm_llama, prompts):
    with pytest.raises(ValueError, match="role and content must be provided in prompt"):
        await llm_llama.generate_response(prompts=prompts)