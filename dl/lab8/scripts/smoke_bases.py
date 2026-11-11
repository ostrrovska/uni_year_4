r"""Статична перевірка чотирьох баз без GPU і без завантаження ваг ImageNet.

Ловить саме ті помилки, які інакше вилізли б у Colab через півгодини прогону:
назва шару в unfreeze_from, розмірність вектора ознак, і головне — чи не став
якийсь BatchNormalization навчаним після розморожування.

Запуск:  PYTHONUTF8=1 ..\lab7\.venv\Scripts\python.exe scripts\smoke_bases.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_notebooks import CONFIGS  # noqa: E402

from tensorflow.keras import layers, models, optimizers  # noqa: E402
from tensorflow.keras import applications  # noqa: E402

INPUT_SIZE = 224


def check(cfg):
    ctor = getattr(applications, cfg["ctor"])

    # weights=None: перевіряємо структуру, а не ваги (інакше 500 МБ завантаження).
    base_feat = ctor(weights=None, include_top=False, pooling="avg",
                     input_shape=(INPUT_SIZE, INPUT_SIZE, 3))
    feat_dim = base_feat.output_shape[-1]
    assert feat_dim == cfg["feat_dim"], \
        f"{cfg['title']}: feat_dim {feat_dim}, а в конфігурації {cfg['feat_dim']}"

    base = ctor(weights=None, include_top=False, input_shape=(INPUT_SIZE, INPUT_SIZE, 3))
    base.trainable = False

    names = [l.name for l in base.layers]
    assert cfg["unfreeze_from"] in names, \
        f"{cfg['title']}: шару {cfg['unfreeze_from']} немає в мережі"

    # Та сама голова, що в ноутбуці.
    inputs = layers.Input(shape=(INPUT_SIZE, INPUT_SIZE, 3))
    x = base(inputs, training=False)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dense(256, activation="relu")(x)
    x = layers.Dropout(0.5)(x)
    outputs = layers.Dense(1, activation="sigmoid")(x)
    model = models.Model(inputs, outputs)
    model.compile(optimizer=optimizers.Adam(1e-4), loss="binary_crossentropy",
                  metrics=["accuracy"])
    total = int(model.count_params())
    trainable_b = int(sum(np.prod(w.shape) for w in model.trainable_weights))

    # Та сама логіка розморожування, що в клітинці етапу C.
    base.trainable = True
    set_trainable = False
    frozen_bn = 0
    for layer in base.layers:
        if layer.name == cfg["unfreeze_from"]:
            set_trainable = True
        layer.trainable = set_trainable
        if isinstance(layer, layers.BatchNormalization):
            layer.trainable = False
            frozen_bn += 1
    model.compile(optimizer=optimizers.Adam(1e-5), loss="binary_crossentropy",
                  metrics=["accuracy"])
    trainable_c = int(sum(np.prod(w.shape) for w in model.trainable_weights))

    unfrozen = [l.name for l in base.layers if l.trainable]
    total_bn = sum(1 for l in base.layers if isinstance(l, layers.BatchNormalization))
    bad_bn = [l.name for l in base.layers
              if isinstance(l, layers.BatchNormalization) and l.trainable]
    assert not bad_bn, f"{cfg['title']}: навчані BatchNormalization: {bad_bn}"
    assert trainable_c > trainable_b, \
        f"{cfg['title']}: розморожування не додало навчаних параметрів"
    assert unfrozen, f"{cfg['title']}: не розморожено жодного шару"

    # Форми: один прогін на випадковому батчі.
    out = model.predict(np.random.rand(2, INPUT_SIZE, INPUT_SIZE, 3).astype("float32"),
                        verbose=0)
    assert out.shape == (2, 1), f"{cfg['title']}: вихід {out.shape}, очікувався (2, 1)"

    print(f"{cfg['title']:<14} шарів {len(base.layers):>4} | ознак {feat_dim:>5} | "
          f"параметрів {total:>12,} | навчаних B {trainable_b:>10,} | "
          f"C {trainable_c:>10,} | розморожено {len(unfrozen):>3} "
          f"(з {cfg['unfreeze_from']}) | BN {total_bn:>3}, усі заморожені")

    alt = cfg["alt_size"]
    if alt:
        base_alt = ctor(weights=None, include_top=False, pooling="avg",
                        input_shape=(alt, alt, 3))
        assert base_alt.output_shape[-1] == cfg["feat_dim"], \
            f"{cfg['title']}: на вході {alt} розмірність ознак інша"
        print(f"{'':<14} додатковий вхід {alt}x{alt}: ознак "
              f"{base_alt.output_shape[-1]} — ок")


def main():
    for cfg in CONFIGS:
        check(cfg)
    print("\nВсі чотири бази зібрані, назви шарів і розмірності збігаються з конфігурацією.")


if __name__ == "__main__":
    main()
