from typing import Any, Optional
from byoeb_integrations.embeddings.llama_index.azure_openai import AzureOpenAIEmbed
from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
from chromadb import Documents, EmbeddingFunction, Embeddings

class AzureOpenAIEmbeddingFunction(EmbeddingFunction):
    def __init__(
        self,
        model: Optional[str] = None,
        deployment_name: Optional[str] = None,
        api_version: Optional[str] = None,
        azure_endpoint: Optional[str] = None,
        token_provider: Any = None,
        api_key: Optional[str] = None,
        embedding_instance: Optional[Any] = None,
        **kwargs
    ) -> None:
        """
        Initialize ChromaDB-compatible embedding function for Azure OpenAI.
        
        Can be initialized in two ways:
        1. Pass an existing embedding instance (AzureOpenAIEmbed or LlamaIndex embedding function):
           AzureOpenAIEmbeddingFunction(embedding_instance=azure_openai_embed.get_embedding_function())
        2. Create a new embedding instance by providing all required parameters:
           AzureOpenAIEmbeddingFunction(model=..., deployment_name=..., api_version=..., azure_endpoint=..., api_key=...)
        """
        # Check if embedding_instance was provided (either as keyword or in kwargs)
        if embedding_instance is None:
            embedding_instance = kwargs.pop('embedding_instance', None)
        
        if embedding_instance is not None:
            # Reuse existing embedding instance
            if isinstance(embedding_instance, AzureOpenAIEmbed):
                self.__embedding_fn = embedding_instance.get_embedding_function()
            else:
                # Assume it's already a LlamaIndex embedding function
                self.__embedding_fn = embedding_instance
        else:
            # Create new embedding instance (backward compatible)
            if not all([model, deployment_name, api_version, azure_endpoint]):
                raise ValueError(
                    "Either provide 'embedding_instance' or all of: "
                    "model, deployment_name, api_version, azure_endpoint, and (api_key or token_provider)"
                )
            azure_openai_embed = AzureOpenAIEmbed(
                model=model,
                deployment_name=deployment_name,
                azure_endpoint=azure_endpoint,
                token_provider=token_provider,
                api_version=api_version,
                api_key=api_key,
                reuse_client=False
            )
            self.__embedding_fn = azure_openai_embed.get_embedding_function()

    def __call__(self, input: Documents) -> Embeddings:
        return [self.__embedding_fn.get_text_embedding(doc) for doc in input]