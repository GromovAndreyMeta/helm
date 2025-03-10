# mypy: check_untyped_defs = False
from typing import List

from helm.common.tokenization_request import TokenizationToken
from helm.benchmark.adaptation.request_state import RequestState
from helm.common.request import Request
from helm.benchmark.adaptation.adapter_spec import AdapterSpec
from .adapter_factory import AdapterFactory, ADAPT_LANGUAGE_MODELING
from .test_adapter import TestAdapter
from helm.benchmark.scenarios.scenario import Instance, Input, Reference


class TestLanguageModelingAdapter(TestAdapter):
    def test_construct_language_modeling_prompt(self):
        adapter_spec = AdapterSpec(
            method=ADAPT_LANGUAGE_MODELING,
            input_prefix="",
            model="openai/davinci",
            output_prefix="",
            max_tokens=0,
        )
        adapter = AdapterFactory.get_adapter(adapter_spec, self.tokenizer_service)

        # The tokens translate to: '�Excuse me�'
        conditioning_tokens: List[TokenizationToken] = [TokenizationToken(110), TokenizationToken(40127)]
        pred_tokens: List[TokenizationToken] = [TokenizationToken(1904), TokenizationToken(502), TokenizationToken(447)]
        prompt, num_conditioning_tokens = adapter.construct_language_modeling_prompt(
            conditioning_tokens=conditioning_tokens, pred_tokens=pred_tokens, max_req_len=5, text=""
        )

        # Ensure the prompt is correct
        assert prompt == "Excuse me"

        # Ensure the number of conditioning tokens is correct
        assert num_conditioning_tokens == 1

    def test_fits_tokens_within_context_window(self):
        adapter_spec = AdapterSpec(
            method=ADAPT_LANGUAGE_MODELING,
            input_prefix="",
            model="openai/curie",
            output_prefix="",
            max_tokens=0,
        )
        adapter = AdapterFactory.get_adapter(adapter_spec, self.tokenizer_service)

        # The tokens translate to: '<|endoftext|>The the the the ... the the'
        # There are 1 `conditioning_token` and 2049 `pred_tokens`. Since the `max_request_length`
        # of GPT-3 is 2049, calling `fits_tokens_within_context_window` will remove the last `pred_token`
        conditioning_tokens: List[TokenizationToken] = [TokenizationToken(50256)]
        pred_tokens: List[TokenizationToken] = [TokenizationToken(464)] + [TokenizationToken(262)] * 2048
        prompt, pred_tokens = adapter.fits_tokens_within_context_window(
            conditioning_tokens, pred_tokens, adapter.window_service.max_request_length
        )

        # Ensure the prompt is correct
        assert prompt == "<|endoftext|>The" + " the" * 2047

        # Ensure the pred_tokens are correct
        assert pred_tokens == [TokenizationToken(464)] + [TokenizationToken(262)] * 2047

    def test_prompt_truncated(self):
        # Step 1. Test that the prompt is trucanted correctly when it is too long
        # anthropic/claude/v1.3 has the following limits:
        #   max_sequence_length = 8000
        #   max_request_length = 8000
        #   max_sequence_and_generated_tokens_length = 9016
        #   max_generated_max_tokens = 8192
        adapter_spec = AdapterSpec(
            method=ADAPT_LANGUAGE_MODELING,
            input_prefix="",
            model="anthropic/claude-v1.3",
            output_prefix="",
            max_tokens=0,
        )
        adapter = AdapterFactory.get_adapter(adapter_spec, self.tokenizer_service)

        # Step 1.1. Check that if the prompt is not too long, it is not truncated
        input_text: Input = Input(text="Excuse me, do you have the time?")
        reference: Reference = Reference(output="Yes, it's 12:30.", tags=[])
        instance: Instance = Instance(
            input=input_text,
            references=[reference],
        )
        # Ensure the adapter returns the correct prompt
        request_states: List[RequestState] = adapter.generate_requests(instance)
        request: Request = request_states[0].request
        # The prompt should be "<|endoftext|>Excuse me, do you have the time?"
        assert request.prompt == "<|endoftext|>Excuse me, do you have the time?"

        # Step 1.2. Check that if the prompt is too long, it is truncated
        input_text_long: Input = Input(text="Excuse me, do you have the time? " * 1000)
        instance_long: Instance = Instance(
            input=input_text_long,
            references=[reference],
        )
        request_states_long: List[RequestState] = adapter.generate_requests(instance_long)
        request_long: Request = request_states_long[0].request
        # Count the number of tokens of the prompt
        num_tokens = len(adapter.window_service.encode(request_long.prompt).token_values)
        assert num_tokens == adapter.window_service.max_request_length

        # Step 2. Test that the prompt is truncated when max_tokens + prompt is too long
        adapter_spec_2_ = AdapterSpec(
            method=ADAPT_LANGUAGE_MODELING,
            input_prefix="",
            model="anthropic/claude-v1.3",
            output_prefix="",
            max_tokens=2000,
        )
        adapter_2 = AdapterFactory.get_adapter(adapter_spec_2_, self.tokenizer_service)

        # Step 2.1. Check that if the prompt is not too long, it is not truncated
        request_state_2: List[RequestState] = adapter_2.generate_requests(instance)
        request_2: Request = request_state_2[0].request
        # The prompt should be unchanged
        assert request_2.prompt == "<|endoftext|>Excuse me, do you have the time?"
        assert request_2.max_tokens == 2000

        # Step 2.2. Check that if the prompt + max_tokens is too long, it is truncated
        # but that we keep the same number of tokens as in the previous test
        request_states_long_2: List[RequestState] = adapter_2.generate_requests(instance_long)
        request_long_2: Request = request_states_long_2[0].request
        # Count the number of tokens of the prompt
        num_tokens_2 = len(adapter_2.window_service.encode(request_long_2.prompt).token_values)
        assert num_tokens_2 == adapter.window_service.max_sequence_and_generated_tokens_length - 2000
        assert request_long_2.max_tokens == 2000
