"""Literal generation contracts without loading torch or a model."""
from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
import math

from scripts.student_test_formula_inference import bounded_prediction, generation_completed
from scripts.student_test_unimernet_worker import infer_prediction


class Tokens:
    def __init__(self, values):
        self.values = values
        self.shape = (1, len(values))

    def __getitem__(self, key):
        selected = self.values[key[1]]
        return Tokens(selected if isinstance(selected, list) else [selected])

    def __eq__(self, value):
        return SimpleNamespace(any=lambda: SimpleNamespace(item=lambda: value in self.values))

    def unsqueeze(self, _dim):
        return self


class Prepared:
    shape = (1, 3, 192, 672)

    def unsqueeze(self, _dim):
        return self

    def to(self, _device):
        return self


class Probability(float):
    def detach(self):
        return self

    def cpu(self):
        return self


class Scores:
    def __init__(self, value):
        self.value = value

    def gather(self, _dim, _chosen):
        return self

    def squeeze(self, _dim):
        return self

    def __getitem__(self, _index):
        return Probability(self.value)


def fake_runtime(tokens, probabilities, text="1/2"):
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(sequences=Tokens([0, *tokens]), scores=probabilities)

    model = SimpleNamespace(model=SimpleNamespace(model=SimpleNamespace(generate=generate)), max_seq_len=1536,
        maybe_autocast=nullcontext,
        tokenizer=SimpleNamespace(tokenizer=SimpleNamespace(bos_token_id=0, eos_token_id=2), token2str=lambda _ids: [text]))
    torch = SimpleNamespace(inference_mode=nullcontext, softmax=lambda value, dim: Scores(value))
    return torch, model, lambda _image: Prepared(), "cpu", calls


def run():
    assertions = 0
    for count, eos, expected in ((63, True, True), (64, True, False), (3, False, False), (0, True, False)):
        assert generation_completed(count, 64, eos) is expected
        assertions += 1
    torch, model, processor, device, calls = fake_runtime([8, 2], [.25, 1])
    runtime = infer_prediction(torch, model, processor, device, object())
    evaluation = bounded_prediction(torch, model, processor, device, object())
    assert runtime["text"] == evaluation["text"] == "1/2"
    assert runtime["terminated"] is evaluation["terminated"] is True
    assert runtime["tokenCount"] == evaluation["tokenCount"] == 2
    assert math.isclose(runtime["tokenConfidence"], .5) and runtime["minTokenConfidence"] == .25
    assert all(call["max_new_tokens"] == 64 and call["do_sample"] is False for call in calls)
    assert calls[0]["output_scores"] is True and calls[1]["output_scores"] is False
    assertions += 6
    for tokens, scores in (([8] * 63 + [2], [1] * 64), ([8, 9], [1, 1]),
                           ([8, 2], [float("nan"), 1]), ([8, 2], [float("inf"), 1]),
                           ([8, 2], [1.1, 1]), ([8, 2], []), ([8, 2], [1])):
        torch, model, processor, device, _calls = fake_runtime(tokens, scores)
        result = infer_prediction(torch, model, processor, device, object())
        assert result["tokenConfidence"] is None and result["minTokenConfidence"] is None
        assertions += 1
    torch, model, processor, device, _calls = fake_runtime([8, 2], [1, 1], "x" * 180)
    assert infer_prediction(torch, model, processor, device, object())["text"] == "x" * 180
    assertions += 1
    return {"passed": True, "assertions": assertions}


if __name__ == "__main__":
    print(run())
