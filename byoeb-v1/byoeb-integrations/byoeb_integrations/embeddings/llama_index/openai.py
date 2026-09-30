from typing import Optional
from llama_index.embeddings.openai import OpenAIEmbedding
from byoeb_core.embeddings.base import BaseEmbedding

class OpenAIEmbed(BaseEmbedding):
    def __init__(
            self,
            model: str,
            dimensions: Optional[int] =None,
            api_key: Optional[str] = None,
            base_url: Optional[str] = None,
            **kwargs
        ) -> None:
            embedding_fn = None
            if model is None:
                raise ValueError("model must be provided")
            if api_key is None and base_url is None:
                raise ValueError("api_key must be provided when base_url is not set")
            # model_name skips llama-index's fixed list of OpenAI model names, so a self-hosted model works
            embedding_fn = OpenAIEmbedding(
                model_name=model,
                dimensions=dimensions,
                api_key=api_key,
                api_base=base_url,
                reuse_client=False
            )

            self.__embedding_fn = embedding_fn

    def get_embedding_function(self):
        return self.__embedding_fn