"""Bounded deterministic formula inference for offline experiments only."""
from __future__ import annotations


def generation_completed(token_count, max_tokens, eos_seen):
    # Some decoders force EOS at max length. EOS alone cannot prove completion.
    return bool(eos_seen and token_count < max_tokens)


def bounded_prediction(torch, model, processor, device, image, max_tokens):
    prepared = processor(image).unsqueeze(0).to(device)
    if prepared.shape[1] == 1:
        prepared = prepared.repeat(1, 3, 1, 1)
    with torch.inference_mode(), model.maybe_autocast():
        generated = model.model.model.generate(
            pixel_values=prepared, max_new_tokens=max_tokens,
            decoder_start_token_id=model.tokenizer.tokenizer.bos_token_id,
            do_sample=False, return_dict_in_generate=True, output_scores=False,
        )
    tokens = generated.sequences[:, 1:]
    text = str(model.tokenizer.token2str(tokens)[0]).strip()
    eos = model.tokenizer.tokenizer.eos_token_id
    count = int(tokens.shape[1])
    eos_seen = eos is not None and bool((tokens == eos).any().item())
    return {"text": text, "terminated": generation_completed(count, max_tokens, eos_seen), "tokenCount": count}
