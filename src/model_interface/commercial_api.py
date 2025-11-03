"""
Commercial API model interface implementation
Supports OpenAI, Anthropic, Google and other APIs
"""
import os
import time
import asyncio
import logging
from typing import Dict, Any, List, Optional
from openai import OpenAI, AsyncOpenAI
import httpx
from anthropic import Anthropic, AsyncAnthropic
import google.generativeai as genai
from .base import ModelInterface

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Request rate limiter
    """
    
    def __init__(self, rpm_limit: int, tpm_limit: int):
        """
        Initialize rate limiter

        Args:
            rpm_limit: Requests per minute (use -1 for unlimited)
            tpm_limit: Tokens per minute (use -1 for unlimited)
        """
        self.rpm_limit = float('inf') if rpm_limit == -1 else rpm_limit
        self.tpm_limit = float('inf') if tpm_limit == -1 else tpm_limit
        self.request_timestamps = []
        self.token_usage = []
        self.lock = asyncio.Lock()
    
    async def wait_if_needed(self, estimated_tokens: int = 1000) -> None:
        """
        Wait if needed to respect rate limits.

        Args:
            estimated_tokens: Estimated token usage
        """
        # Return early if unlimited
        if self.rpm_limit == float('inf') and self.tpm_limit == float('inf'):
            return
            
        async with self.lock:
            current_time = time.time()
            
            # Remove records older than one minute
            one_minute_ago = current_time - 60
            self.request_timestamps = [t for t in self.request_timestamps if t > one_minute_ago]
            self.token_usage = [(t, tokens) for t, tokens in self.token_usage if t > one_minute_ago]
            
            # Check RPM limit
            if self.rpm_limit != float('inf') and len(self.request_timestamps) >= self.rpm_limit:
                oldest_timestamp = self.request_timestamps[0]
                wait_time = 60 - (current_time - oldest_timestamp)
                if wait_time > 0:
                    logger.info(f"Waiting {wait_time:.2f}s to respect RPM limit")
                    await asyncio.sleep(wait_time)
            
            # Check TPM limit
            if self.tpm_limit != float('inf'):
                current_token_usage = sum(tokens for _, tokens in self.token_usage)
                if current_token_usage + estimated_tokens > self.tpm_limit:
                    oldest_token_timestamp = self.token_usage[0][0]
                    wait_time = 60 - (current_time - oldest_token_timestamp)
                    if wait_time > 0:
                        logger.info(f"Waiting {wait_time:.2f}s to respect TPM limit")
                        await asyncio.sleep(wait_time)
            
            # Update records
            self.request_timestamps.append(time.time())
            self.token_usage.append((time.time(), estimated_tokens))

class CommercialAPIInterface(ModelInterface):
    """
    Commercial API model interface
    """
    
    def __init__(self, model_config: Dict[str, Any], api_key: Optional[str] = None):
        """
        Initialize commercial API model interface

        Args:
            model_config: Model configuration
            api_key: API key (falls back to env var if omitted)
        """
        super().__init__(model_config)
        self.provider = model_config.get('provider', '').lower()
        self.base_url = model_config.get('base_url')
        self.model_id = model_config.get('model_id')
        
        # Resolve API key
        self.api_key = api_key or os.environ.get(f"{self.provider.upper()}_API_KEY")
        if not self.api_key:
            raise ValueError(f"API key for {self.provider} not provided and not found in environment")
        
        # Init rate limiter
        rpm_limit = model_config.get('rpm_limit', 60)
        tpm_limit = model_config.get('tpm_limit', 60000)
        
        # Track unlimited modes
        self.unlimited_rpm = rpm_limit == -1
        self.unlimited_tpm = tpm_limit == -1
        self.rate_limiter = RateLimiter(rpm_limit, tpm_limit)
        
        # Initialize API client
        self._init_client()
    
    def _init_client(self):
        """
        Initialize API client
        """
        if self.provider == 'openai':
            # Build httpx clients explicitly to avoid openai/httpx version mismatch on proxy args
            timeout = httpx.Timeout(1200.0)
            # Prefer HTTPS proxy; fall back to HTTP
            proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or \
                        os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")

            sync_client = None
            async_client = None
            try:
                # Try old-style 'proxies' kw (httpx < 0.28)
                sync_client = httpx.Client(timeout=timeout, verify=True, proxies=proxy_url) if proxy_url else httpx.Client(timeout=timeout, verify=True)
            except TypeError:
                # Fallback for httpx >= 0.28 using 'proxy'
                sync_client = httpx.Client(timeout=timeout, verify=True, proxy=proxy_url) if proxy_url else httpx.Client(timeout=timeout, verify=True)

            try:
                async_client = httpx.AsyncClient(timeout=timeout, verify=True, proxies=proxy_url) if proxy_url else httpx.AsyncClient(timeout=timeout, verify=True)
            except TypeError:
                async_client = httpx.AsyncClient(timeout=timeout, verify=True, proxy=proxy_url) if proxy_url else httpx.AsyncClient(timeout=timeout, verify=True)

            self.client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                http_client=sync_client,
            )
            self.async_client = AsyncOpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                http_client=async_client,
            )
        elif self.provider == 'anthropic':
            self.client = Anthropic(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=1200.0
            )
            self.async_client = AsyncAnthropic(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=1200.0
            )
        elif self.provider == 'google':
            genai.configure(
                api_key=self.api_key,
                transport="rest",
                client_options={"api_endpoint": self.base_url},
            )
            self.client = genai
            self.async_client = None  # Google API SDK here doesn't support async calls
        else:
            raise ValueError(f"Unsupported API provider: {self.provider}")
    
    async def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate model response asynchronously
        
        Args:
            prompt: Input prompt
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing the model response
        """
        # Estimate token count, simply assume 4 characters ≈ 1 token
        # estimated_tokens = len(prompt) // 4 + 1000  # Add 1000 as an estimate for the reply
        estimated_tokens = 10000 # average tokens
        
        # Wait if needed for rate limiting
        await self.rate_limiter.wait_if_needed(estimated_tokens)
        
        if self.provider == 'openai':
            return await self._generate_openai_stream(prompt, **kwargs)
        elif self.provider == 'anthropic':
            max_tokens = kwargs.get('max_tokens', self.model_config.get('max_tokens', 4096))
            # if max_tokens > 0:
            #     return await self._stream_anthropic(prompt, **kwargs)
            # else:
            return await self._generate_anthropic(prompt, **kwargs)
        elif self.provider == 'google':
            # Use thread pool to call sync method asynchronously
            return await self._generate_google_async(prompt, **kwargs)
            # return self._generate_google_sync(prompt, **kwargs)
        else:
            raise ValueError(f"Unsupported API provider: {self.provider}")
    
    def generate_sync(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate model response synchronously
        
        Args:
            prompt: Input prompt
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing the model response
        """
        if self.provider == 'openai':
            return self._generate_openai_sync(prompt, **kwargs)
        elif self.provider == 'anthropic':
            return self._generate_anthropic_sync(prompt, **kwargs)
        elif self.provider == 'google':
            return self._generate_google_sync(prompt, **kwargs)
        else:
            raise ValueError(f"Unsupported API provider: {self.provider}")
    
    async def _generate_openai(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate response using OpenAI API asynchronously
        """
        max_tokens = kwargs.get('max_tokens', self.model_config.get('max_tokens', 4096))
        
        try:
            response = await self.async_client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=self.model_id,
                max_completion_tokens=max_tokens,
                stream=False,
                **kwargs
            )
            
            # Default return payload
            result = {
                'text': response.choices[0].message.content,
                'model': self.model_id,
                'finish_reason': response.choices[0].finish_reason,
                'usage': {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens
                },
                'raw_response': response
            }
            # Add reasoning_content for deepseek-reasoner
            if self.model_id == "deepseek-reasoner":
                result['reasoning_content'] = getattr(response.choices[0].message, "reasoning_content", None)
            return result
        
        except Exception as e:
            logger.error(f"OpenAI API call failed: {str(e)}")
            return {
                'error': str(e),
                'model': self.model_id,
                'text': None
            }
    
    async def _generate_openai_stream(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate response using OpenAI API asynchronously
        """
        max_tokens = kwargs.get('max_tokens', self.model_config.get('max_tokens', 4096))
        
        try:
            response = await self.async_client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=self.model_id,
                max_completion_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
                **kwargs
            )
            
            answer_stream = []
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            last_chunk = None
            reasoning_content_stream = []  # to accumulate reasoning_content
            
            async for chunk in response:
                last_chunk = chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    prompt_tokens = chunk.usage.prompt_tokens
                    completion_tokens = chunk.usage.completion_tokens
                    total_tokens = chunk.usage.total_tokens
                if not hasattr(chunk, "choices") or not chunk.choices:
                    continue  # Safety check
                delta = chunk.choices[0].delta.content if chunk.choices[0].delta else None
                if delta:
                    answer_stream.append(delta)
                # Accumulate reasoning_content
                if self.model_id in ["deepseek-reasoner", "deepseek-ai/DeepSeek-R1"]:
                    rc = getattr(chunk.choices[0].delta, "reasoning_content", None) if chunk.choices[0].delta else None
                    if rc is not None:
                        reasoning_content_stream.append(rc)
            answer = "".join(answer_stream)
                
            finish_reason = None
            if last_chunk and hasattr(last_chunk, "choices") and last_chunk.choices:
                finish_reason = last_chunk.choices[0].finish_reason
            # Default return payload
            result = {
                'text': answer,
                'model': self.model_id,
                'finish_reason': chunk.choices[0].finish_reason if chunk.choices else None,
                'usage': {
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'total_tokens': total_tokens
                },
                'raw_response': response
            }
            # Attach concatenated reasoning_content if applicable
            if self.model_id in ["deepseek-reasoner", "deepseek-ai/DeepSeek-R1"]:
                result['reasoning_content'] = "".join(reasoning_content_stream)
            return result
        
        except Exception as e:
            logger.error(f"OpenAI API call failed: {str(e)}")
            return {
                'error': str(e),
                'model': self.model_id,
                'text': None
            }
        
    def _generate_openai_sync(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate response using OpenAI API synchronously
        """
        max_tokens = kwargs.get('max_tokens', self.model_config.get('max_tokens', 4096))
        
        try:
            response = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=self.model_id,
                max_tokens=max_tokens,
                stream=False,
                **kwargs
            )
            
            result = {
                'text': response.choices[0].message.content,
                'model': self.model_id,
                'finish_reason': response.choices[0].finish_reason,
                'usage': {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens
                },
                'raw_response': response
            }
            if self.model_id == "deepseek-reasoner":
                result['reasoning_content'] = getattr(response.choices[0].message, "reasoning_content", None)
            return result
        except Exception as e:
            logger.error(f"OpenAI API call failed: {str(e)}")
            return {
                'error': str(e),
                'model': self.model_id,
                'text': None
            }
    
    async def _generate_anthropic(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate response using Anthropic API asynchronously
        """
        max_tokens = kwargs.get('max_tokens', self.model_config.get('max_tokens', 4096))
        
        try:
            response = await self.async_client.messages.create(
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=self.model_id,
                **kwargs
            )
            
            return {
                'text': response.content[0].text,
                'model': self.model_id,
                'usage': {
                    'input_tokens': response.usage.input_tokens,
                    'output_tokens': response.usage.output_tokens
                },
                'raw_response': response
            }
        except Exception as e:
            logger.error(f"Anthropic API call failed: {str(e)}")
            return {
                'error': str(e),
                'model': self.model_id,
                'text': None
            }
    
    def _generate_anthropic_sync(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate response using Anthropic API synchronously
        """
        max_tokens = kwargs.get('max_tokens', self.model_config.get('max_tokens', 4096))
        
        try:
            response = self.client.messages.create(
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=self.model_id,
                **kwargs
            )
            
            return {
                'text': response.content[0].text,
                'model': self.model_id,
                'usage': {
                    'input_tokens': response.usage.input_tokens,
                    'output_tokens': response.usage.output_tokens
                },
                'raw_response': response
            }
        except Exception as e:
            logger.error(f"Anthropic API call failed: {str(e)}")
            return {
                'error': str(e),
                'model': self.model_id,
                'text': None
            }
    
    def _generate_google_sync(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate response using Google Gemini API
        """
        try:
            model = self.client.GenerativeModel(self.model_id)
            response = model.generate_content(prompt, **kwargs)
            
            return {
                'text': response.text,
                'model': self.model_id,
                'usage': {
                    'input_tokens': response.usage_metadata.prompt_token_count,
                    'completion_tokens': response.usage_metadata.candidates_token_count,
                    'total_tokens': response.usage_metadata.total_token_count
                },
                'raw_response': response
            }
        except Exception as e:
            logger.error(f"Google API call failed: {str(e)}")
            return {
                'error': str(e),
                'model': self.model_id,
                'text': None
            }
    
    async def _generate_google_async(self, prompt: str, **kwargs) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        # Use thread pool to run sync method asynchronously
        return await loop.run_in_executor(
            None,  # Use default thread pool
            lambda: self._generate_google_sync(prompt, **kwargs)
        )
    
    async def _stream_anthropic(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Stream response from Anthropic API (async) and return full text and token usage.
        """
        max_tokens = kwargs.get('max_tokens', self.model_config.get('max_tokens', 4096))
        try:
            stream = await self.async_client.messages.create(
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=self.model_id,
                stream=True,
                **kwargs
            )
            full_text = ""
            input_tokens = 0
            output_tokens = 0
            # Iterate through Anthropic streaming events
            async for event in stream:
                # Append text deltas only
                if hasattr(event, "delta") and hasattr(event.delta, "text"):
                    full_text += event.delta.text
                # Track token usage
                if hasattr(event, "usage"):
                    if hasattr(event.usage, "input_tokens"):
                        input_tokens = event.usage.input_tokens
                    if hasattr(event.usage, "output_tokens"):
                        output_tokens = event.usage.output_tokens
            return {
                'text': full_text,
                'model': self.model_id,
                'usage': {
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens
                },
                'raw_response': None  # No single full response in streaming
            }
        except Exception as e:
            logger.error(f"Anthropic streaming API call failed: {str(e)}")
            return {
                'error': str(e),
                'model': self.model_id,
                'text': None
            }
    
    async def _generate_openai_responses(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate response using OpenAI Responses API asynchronously.
        """
        max_tokens = kwargs.get('max_tokens', self.model_config.get('max_tokens', 4096))
        try:
            # Support either raw string prompt or messages structure
            input_data = kwargs.get('input', None)
            if input_data is not None:
                input_for_api = input_data
            else:
                input_for_api = prompt

            response = await self.async_client.responses.create(
                model=self.model_id,
                reasoning={"effort": "high"},
                input=input_for_api,
                max_output_tokens=max_tokens,
                stream=False,
                **kwargs
            )
            
            # Normalize responses API output structure
            text = ""
            if hasattr(response, 'output') and response.output:
                for output in response.output:
                    if hasattr(output, 'content') and output.content:
                        for content in output.content:
                            if hasattr(content, 'text') and content.text:
                                text += content.text

            result = {
                'text': text,
                'model': self.model_id,
                'finish_reason': getattr(response, 'finish_reason', None),
                'usage': getattr(response, 'usage', {}),
                'raw_response': response
            }
            return result

        except Exception as e:
            logger.error(f"OpenAI Responses API call failed: {str(e)}")
            return {
                'error': str(e),
                'model': self.model_id,
                'text': None
            } 