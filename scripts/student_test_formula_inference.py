"""Shared deterministic generation contract for runtime and offline evaluation."""
from __future__ import annotations

import math

MAX_FORMULA_TOKENS = 64


def generation_completed(token_count, max_tokens, eos_seen):
    # Some decoders force EOS at max length. EOS alone cannot prove completion.
    return bool(eos_seen and 0 < token_count < max_tokens)


def bounded_prediction(torch, model, processor, device, image, max_tokens=MAX_FORMULA_TOKENS, *, output_scores=False):
    if type(max_tokens) is not int or max_tokens < 2:
        raise ValueError("formula generation limit must be an integer greater than one")
    prepared = processor(image).unsqueeze(0).to(device)
    if prepared.shape[1] == 1:
        prepared = prepared.repeat(1, 3, 1, 1)
    with torch.inference_mode(), model.maybe_autocast():
        generated = model.model.model.generate(
            pixel_values=prepared, max_new_tokens=max_tokens,
            decoder_start_token_id=model.tokenizer.tokenizer.bos_token_id,
            do_sample=False, return_dict_in_generate=True, output_scores=output_scores,
        )
    tokens = generated.sequences[:, 1:]
    text = str(model.tokenizer.token2str(tokens)[0]).strip()
    eos = model.tokenizer.tokenizer.eos_token_id
    count = int(tokens.shape[1])
    eos_seen = eos is not None and bool((tokens == eos).any().item())
    result = {"text": text, "terminated": generation_completed(count, max_tokens, eos_seen), "tokenCount": count}
    if output_scores:
        probabilities = []
        for index, logits in enumerate(generated.scores):
            if index >= count:
                break
            chosen = tokens[:, index].unsqueeze(-1)
            probability = torch.softmax(logits, dim=-1).gather(1, chosen).squeeze(-1)
            probabilities.append(float(probability[0].detach().cpu()))
        scores_valid = len(probabilities) == count and all(math.isfinite(p) and 0 <= p <= 1 for p in probabilities)
        result["tokenConfidence"] = (
            math.exp(sum(math.log(max(p, 1e-12)) for p in probabilities) / count)
            if result["terminated"] and scores_valid else None
        )
        result["minTokenConfidence"] = min(probabilities) if result["terminated"] and scores_valid else None
    return result
