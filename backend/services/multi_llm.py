import os
import logging
import json
from dotenv import load_dotenv
from groq import Groq, RateLimitError as GroqRateLimitError
import google.generativeai as genai

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- LLM Provider Configuration ---
# Priority-ordered list of LLM providers
PROVIDERS = [
    {'name': 'groq_70b', 'type': 'groq', 'model': 'llama3-70b-8192', 'priority': 1},
    {'name': 'gemini_pro', 'type': 'gemini', 'model': 'gemini-1.5-pro-latest', 'priority': 2},
    {'name': 'groq_8b', 'type': 'groq', 'model': 'llama3-8b-8192', 'priority': 3},
]

# --- Groq API Integration ---
def call_groq(prompt: str, system: str, model: str, temperature: float, max_tokens: int) -> str:
    """
    Calls the Groq API with the given parameters.

    Args:
        prompt (str): The user prompt.
        system (str): The system message.
        model (str): The Groq model to use.
        temperature (float): The sampling temperature.
        max_tokens (int): The maximum number of tokens to generate.

    Returns:
        str: The response text from the LLM.

    Raises:
        RuntimeError: If the Groq API call fails for any reason other than rate limiting.
        GroqRateLimitError: If the API rate limit is exceeded.
    """
    try:
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        
        chat_completion = client.chat.completions.create(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        response_text = chat_completion.choices[0].message.content
        if not response_text:
            raise ValueError("Received an empty response from Groq.")
        return response_text
    except GroqRateLimitError as e:
        raise e  # Re-raise to be handled by the smart caller
    except Exception as e:
        logging.error(f"Groq API call failed for model {model}: {e}")
        raise RuntimeError(f"Groq API call failed: {e}") from e

# --- Gemini API Integration ---
def call_gemini(prompt: str, system: str, model: str, temperature: float, max_tokens: int) -> str:
    """
    Calls the Google Gemini API with the given parameters.

    Args:
        prompt (str): The user prompt.
        system (str): The system message (prepended to the user prompt).
        model (str): The Gemini model to use.
        temperature (float): The sampling temperature.
        max_tokens (int): The maximum number of tokens to generate.

    Returns:
        str: The response text from the LLM.

    Raises:
        RuntimeError: If the Gemini API key is not configured or the call fails.
    """
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        raise RuntimeError("Gemini not configured: GEMINI_API_KEY environment variable is missing.")
    
    try:
        genai.configure(api_key=gemini_api_key)
        
        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        
        # Gemini combines system and user prompts
        full_prompt = f"{system}\n\n{prompt}"
        
        gemini_model = genai.GenerativeModel(model_name=model)
        response = gemini_model.generate_content(full_prompt, generation_config=generation_config)
        
        return response.text
    except Exception as e:
        # The Gemini SDK can raise a variety of exceptions, including google.api_core.exceptions
        logging.error(f"Gemini API call failed for model {model}: {e}")
        if "rate limit" in str(e).lower():
             # Create a consistent error type for rate limiting
             raise GroqRateLimitError("Gemini rate limit exceeded.")
        raise RuntimeError(f"Gemini API call failed: {e}") from e

# --- Smart LLM Dispatcher ---
def smart_llm_call(prompt: str, system: str = "", temperature: float = 0.1, max_tokens: int = 1000, prefer_provider: str = None) -> dict:
    """
    Tries each LLM provider in priority order with automatic fallback.

    Args:
        prompt (str): The user prompt.
        system (str): The system message.
        temperature (float): The sampling temperature.
        max_tokens (int): The maximum number of tokens to generate.
        prefer_provider (str, optional): A provider name to try first.

    Returns:
        dict: A dictionary with 'text', 'provider', and 'model' on success.

    Raises:
        RuntimeError: If all LLM providers are exhausted or fail.
    """
    provider_list = sorted(PROVIDERS, key=lambda p: p['priority'])
    available_providers = get_available_providers()

    # If a preferred provider is specified, move it to the front of the list
    if prefer_provider:
        provider_list.sort(key=lambda p: p['name'] != prefer_provider)

    for provider in provider_list:
        provider_name = provider['name']
        
        # Skip providers that are not configured
        if provider_name not in available_providers:
            logging.warning(f"Skipping LLM provider {provider_name} as it is not configured.")
            continue

        logging.info(f"Attempting LLM call with provider: {provider_name} (Model: {provider['model']})")
        
        try:
            # Select the appropriate function based on provider type
            if provider['type'] == 'groq':
                response_text = call_groq(prompt, system, provider['model'], temperature, max_tokens)
            elif provider['type'] == 'gemini':
                response_text = call_gemini(prompt, system, provider['model'], temperature, max_tokens)
            else:
                logging.warning(f"Unknown provider type: {provider['type']}")
                continue

            logging.info(f"LLM call succeeded with provider: {provider_name}")
            return {
                "text": response_text,
                "provider": provider_name,
                "model": provider['model']
            }
        except GroqRateLimitError:
            logging.warning(f"Rate limit exceeded for {provider_name}. Falling back to the next provider.")
            continue
        except RuntimeError as e:
            logging.error(f"Provider {provider_name} failed: {e}. Trying next provider.")
            continue
        except Exception as e:
            logging.critical(f"An unexpected error occurred with provider {provider_name}: {e}")
            continue

    raise RuntimeError("All LLM providers exhausted. The operation could not be completed.")

# --- Utility Functions ---
def get_available_providers() -> list[str]:
    """
    Checks for API keys in environment variables and returns a list of configured providers.
    """
    configured_providers = []
    if os.getenv("GROQ_API_KEY"):
        configured_providers.extend([p['name'] for p in PROVIDERS if p['type'] == 'groq'])
    if os.getenv("GEMINI_API_KEY"):
        configured_providers.extend([p['name'] for p in PROVIDERS if p['type'] == 'gemini'])
    return configured_providers

# --- Module Initialization ---
if __name__ == "__main__":
    logging.info("multi_llm.py loaded OK")
    available = get_available_providers()
    logging.info(f"Available LLM providers: {available if available else 'None'}")
    print("multi_llm.py loaded OK")
else:
    # Log available providers on module import
    _available_providers = get_available_providers()
    logging.info(f"Multi-LLM service initialized. Available providers: {_available_providers if _available_providers else 'None'}")
