import hashlib
import byoeb.services.chat.constants as constants
import re
import byoeb.utils.utils as utils
import random
from datetime import datetime, timezone
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
from typing import List, Dict, Any
from byoeb.chat_app.configuration.config import bot_config, app_config
from byoeb.models.message_category import MessageCategory
from byoeb_core.models.vector_stores.chunk import Chunk
from byoeb_core.models.vector_stores.azure.azure_search import AzureSearchNode
from byoeb_core.models.byoeb.message_context import (
    ByoebMessageContext,
    MessageContext,
    ReplyContext,
    MessageTypes
)
from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorSearchType
from byoeb_core.models.byoeb.user import User
from byoeb.services.chat.message_handlers.base import Handler
from byoeb.chat_app.configuration.dependency_setup import llm_client

class ByoebUserGenerateResponse(Handler):
    EXPERT_PENDING_EMOJI = app_config["channel"]["reaction"]["expert"]["pending"]
    USER_PENDING_EMOJI = app_config["channel"]["reaction"]["user"]["pending"]
    _expert_user_types = bot_config["expert"]
    _regular_user_type = bot_config["regular"]["user_type"]

    async def __aretrieve_chunks(
        self,
        text,
        k
    ) -> List[Chunk]:
        from byoeb.chat_app.configuration.dependency_setup import vector_store
        start_time = datetime.now(timezone.utc).timestamp()
        retrieved_chunks = await vector_store.aretrieve_top_k_chunks(
            text,
            k,
            search_type=AzureVectorSearchType.DENSE.value,
            select=["id", "text", "metadata", "related_questions"],
            vector_field="text_vector_3072"
        )
        end_time = datetime.now(timezone.utc).timestamp()
        utils.log_to_text_file(f"Retrieved chunks in {end_time - start_time} seconds")
        return retrieved_chunks
        
    def __augment(
        self,
        system_prompt,
        user_prompt
    ):
        augmented_prompts = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        return augmented_prompts
    
    def __get_expert_additional_info(
        self,
        texts: List[str],
        emoji = None,
        status = None
    ):
        additional_info = {
            constants.EMOJI: emoji,
            constants.VERIFICATION_STATUS: status,
            "button_titles": bot_config["template_messages"]["expert"]["verification"]["button_titles"],
            "template_name": bot_config["channel_templates"]["expert"]["verification"],
            "template_language": "en",  
            "template_parameters": texts
        }
        return additional_info
    
    def __get_expert_number_and_type(
        self,
        experts: Dict[str, List[Any]],
        query_type = "medical"
    ):
        expert_type = self._expert_user_types.get(query_type)
        if experts is None:
            return None, None
        if expert_type not in experts:
            return None, None
        return experts[expert_type][0], expert_type
    
    def __create_read_reciept_message(
        self,
        message: ByoebMessageContext,
    ) -> ByoebMessageContext:
        read_reciept_message = ByoebMessageContext(
            channel_type=message.channel_type,
            message_category=MessageCategory.READ_RECEIPT.value,
            message_context=MessageContext(
                message_id=message.message_context.message_id,
            )
        )
        return read_reciept_message
    
    async def __create_user_message(
        self,
        message: ByoebMessageContext,
        response_text: str,
        related_questions: List[str] = None,
        emoji = None,
        status = None,
    ) -> ByoebMessageContext:
        from byoeb.chat_app.configuration.dependency_setup import text_translator
        from byoeb.chat_app.configuration.dependency_setup import speech_translator
        user_language = message.user.user_language
        status_info = {
            constants.EMOJI: emoji,
            constants.VERIFICATION_STATUS: status,
        }
        start_time = datetime.now(timezone.utc).timestamp()
        message_source_text = await text_translator.atranslate_text(
            input_text=response_text,
            source_language="en",
            target_language=user_language
        )
        end_time = datetime.now(timezone.utc).timestamp()
        utils.log_to_text_file(f"Translated response message in {end_time - start_time} seconds")
        start_time = datetime.now(timezone.utc).timestamp()
        translated_audio_message = await speech_translator.atext_to_speech(
                input_text=message_source_text,
                source_language=user_language,
        )
        media_info = {
            constants.DATA: translated_audio_message,
            constants.MIME_TYPE: "audio/wav",
        }
        end_time = datetime.now(timezone.utc).timestamp()
        utils.log_to_text_file(f"Created audio response message in {end_time - start_time} seconds")
        description = bot_config["template_messages"]["user"]["follow_up_questions_description"][user_language]
        interactive_list_additional_info = {
            constants.DESCRIPTION: description,
            constants.ROW_TEXTS: related_questions
        }
        message_type = None
        if (message.message_context.message_type == MessageTypes.REGULAR_AUDIO.value):
            message_type = MessageTypes.REGULAR_AUDIO.value
        else:
            message_type = MessageTypes.INTERACTIVE_LIST.value
        user_message = ByoebMessageContext(
            channel_type=message.channel_type,
            message_category=MessageCategory.BOT_TO_USER_RESPONSE.value,
            user=User(
                user_id=message.user.user_id,
                user_language=user_language,
                user_type=self._regular_user_type,
                phone_number_id=message.user.phone_number_id,
                last_conversations=message.user.last_conversations
            ),
            message_context=MessageContext(
                message_type=message_type,
                message_source_text=message_source_text,
                message_english_text=response_text,
                additional_info={
                    **status_info,
                    **media_info,
                    **interactive_list_additional_info
                }
            ),
            reply_context=ReplyContext(
                reply_id=message.message_context.message_id,
                reply_type=message.message_context.message_type,
                reply_english_text=message.message_context.message_english_text,
                reply_source_text=message.message_context.message_source_text,
                media_info=message.message_context.media_info
            ),
            incoming_timestamp=message.incoming_timestamp,
        )
        return user_message
    
    def __create_expert_verification_message(
        self,
        message: ByoebMessageContext,
        response_text: str,
        query_type = "medical",
        emoji = None,
        status = None,
    ) -> ByoebMessageContext:
        
        expert_phone_number_id , expert_type= self.__get_expert_number_and_type(message.user.experts, query_type)
        if expert_phone_number_id is None:
            return None
        expert_user_id = hashlib.md5(expert_phone_number_id.encode()).hexdigest()
        verification_question_template = bot_config["template_messages"]["expert"]["verification"]["Question"]
        verification_bot_answer_template = bot_config["template_messages"]["expert"]["verification"]["Bot_Answer"]
        verification_question = verification_question_template.replace(
            "<QUESTION>",
            message.message_context.message_english_text
        )
        verification_bot_answer = verification_bot_answer_template.replace(
            "<ANSWER>",
            response_text
        )
        verification_footer_message = bot_config["template_messages"]["expert"]["verification"]["footer"]
        additional_info = self.__get_expert_additional_info(
            [verification_question, verification_bot_answer],
            emoji,
            status
        )
        expert_message = verification_question + "\n" + verification_bot_answer + "\n" + verification_footer_message
        new_expert_verification_message = ByoebMessageContext(
            channel_type=message.channel_type,
            message_category=MessageCategory.BOT_TO_EXPERT_VERIFICATION.value,
            user=User(
                user_id=expert_user_id,
                user_type=expert_type,
                user_language='en',
                phone_number_id=expert_phone_number_id
            ),
            message_context=MessageContext(
                message_type=MessageTypes.INTERACTIVE_BUTTON.value,
                message_source_text=expert_message,
                message_english_text=expert_message,
                additional_info=additional_info
            ),
            incoming_timestamp=message.incoming_timestamp,
        )
        return new_expert_verification_message
    
    @retry(
        stop=stop_after_attempt(3),  # Retry up to 3 times
        wait=wait_exponential(multiplier=1, max=10),  # Exponential backoff with a max wait time of 10 seconds
    )
    async def agenerate_answer(
        self,
        question,
        retrieved_chunks: List[Chunk],
    ):
        def parse_response(response_text):
            # Regular expressions to extract the response and relevance
            response_pattern = r"<RESPONSE>(.*?)</RESPONSE>"
            query_type_pattern = r"<QUERY TYPE>(.*?)</QUERY TYPE>"

            # Extract the response
            response_match = re.search(response_pattern, response_text, re.DOTALL)
            response = response_match.group(1).strip() if response_match else None

            # Extract the relevance
            query_type_match = re.search(query_type_pattern, response_text, re.DOTALL)
            query_type = query_type_match.group(1).strip() if query_type_match else None
            return response, query_type
        
        chunks_list = [chunk.text for chunk in retrieved_chunks]
        system_prompt = bot_config["llm_response"]["answer_prompts"]["system_prompt"]
        template_user_prompt = bot_config["llm_response"]["answer_prompts"]["user_prompt"]
        # Replace placeholders with actual values
        chunks = ", ".join(chunks_list)
        user_prompt = template_user_prompt.replace("<CHUNKS>", chunks).replace("<QUESTION>", question)
        augmented_prompts = self.__augment(system_prompt, user_prompt)
        start_time = datetime.now(timezone.utc).timestamp()
        llm_response, response_text = await llm_client.agenerate_response(augmented_prompts)
        tokens = llm_client.get_response_tokens(llm_response)
        answer, query_type = parse_response(response_text)
        end_time = datetime.now(timezone.utc).timestamp()
        utils.log_to_text_file(f"Generated answer tokens and response in {end_time - start_time} seconds: {str(tokens)} {response_text}")
        print("Generated answer: ", answer)
        print("Query type: ", query_type)
        if answer is None or query_type is None:
            raise ValueError("Parsing failed, response or query_type is None.")
        return answer, query_type
    
    @retry(
        stop=stop_after_attempt(3),  # Retry up to 3 times
        wait=wait_exponential(multiplier=1, max=10),  # Exponential backoff with a max wait time of 10 seconds
    )
    async def agenerate_follow_up_questions(
        self,
        retrieved_chunks: List[Chunk],
    ):
        chunks_list = [chunk.text for chunk in retrieved_chunks]
        system_prompt = bot_config["llm_response"]["follow_up_prompts"]["system_prompt"]
        template_user_prompt = bot_config["llm_response"]["follow_up_prompts"]["user_prompt"]
        chunks = ", ".join(chunks_list)
        user_prompt = template_user_prompt.replace("<CHUNKS>", chunks)
        augmented_prompts = self.__augment(system_prompt, user_prompt)
        llm_response, response_text = await llm_client.agenerate_response(augmented_prompts)
        tokens = llm_client.get_response_tokens(llm_response)
        utils.log_to_text_file(f"Generated answer tokens: {str(tokens)}")
        next_questions = re.findall(r"<q_\d+>(.*?)</q_\d+>", response_text)
        if next_questions is None or len(next_questions) != 3:
            raise ValueError("Parsing failed, next_questions.")
        return next_questions
    
    def get_follow_up_questions(
        self,
        user_lang_code: str,
        retrieved_chunks: List[Chunk],
    ):
        all_questions = []

        # Collect all related questions from all chunks
        for retrieved_chunk in retrieved_chunks:
            related_questions = retrieved_chunk.related_questions.get(user_lang_code)
            if related_questions:
                all_questions.extend(related_questions)

        # Filter questions based on length constraint
        valid_questions = [q for q in all_questions if len(q) < 70]

        # Shuffle and pick up to 3
        random.shuffle(valid_questions)
        
        return valid_questions[:3]  # Return at most 3 questions
    
    async def __handle_message_generate_workflow(
        self,
        messages: ByoebMessageContext
    ) -> List[ByoebMessageContext]:
        byoeb_messages = []
        message: ByoebMessageContext = messages[0].model_copy(deep=True)
        read_reciept_message = self.__create_read_reciept_message(message)
        message_english = message.message_context.message_english_text
        retrieved_chunks = await self.__aretrieve_chunks(message_english, k=3)
        answer, query_type = await self.agenerate_answer(message_english, retrieved_chunks)
        related_questions = self.get_follow_up_questions(message.user.user_language, retrieved_chunks)
        byoeb_user_message = await self.__create_user_message(
            message=message,
            response_text=answer,
            emoji=self.USER_PENDING_EMOJI,
            status=constants.PENDING,
            related_questions=related_questions
        )
        print("Created user message")
        byoeb_expert_message = self.__create_expert_verification_message(
            message,
            answer,
            query_type.lower(),
            self.EXPERT_PENDING_EMOJI,
            constants.PENDING
        )
        print("Created expert message")

        # Aggregate all messages
        if byoeb_user_message is not None:
            byoeb_messages.append(byoeb_user_message)
        if byoeb_expert_message is not None:
            byoeb_messages.append(byoeb_expert_message)
        if read_reciept_message is not None:
            byoeb_messages.append(read_reciept_message)
        return byoeb_messages
    
    async def handle(
        self,
        messages: List[ByoebMessageContext]
    ) -> Dict[str, Any]:
        if messages is None or len(messages) == 0:
            return {}
        new_messages = []
        try:
            start_time = datetime.now(timezone.utc).timestamp()
            new_messages = await self.__handle_message_generate_workflow(messages)
            end_time = datetime.now(timezone.utc).timestamp()
            utils.log_to_text_file(f"E2E Generated answer and related questions in {end_time - start_time} seconds")
        except RetryError as e:
            utils.log_to_text_file(f"RetryError in generating response: {e}")
            print("RetryError in generating response: ", e)
            raise e
        except Exception as e:
            utils.log_to_text_file(f"Error in generating response: {e}")
            print("Error in generating response: ", e)
            raise e
        if self._successor:
            return await self._successor.handle(
                new_messages
            )