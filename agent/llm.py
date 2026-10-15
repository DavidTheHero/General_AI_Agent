"""LangChain prompts and Ollama model configuration."""

import os

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama


def create_chat_model() -> ChatOllama:
    return ChatOllama(
        model=os.environ.get("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M"),
        base_url=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        temperature=0,
    )


def build_chain(model, schema, user_template: str):
    parser = PydanticOutputParser(pydantic_object=schema)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "{instructions}\nReturn only JSON.\n{format_instructions}"),
        ("human", user_template),
    ]).partial(
        instructions=schema.__doc__,
        format_instructions=parser.get_format_instructions(),
    )
    return prompt | model.bind(format=schema.model_json_schema()) | parser
