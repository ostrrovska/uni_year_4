"""Замір швидкості навчання на CPU: скільки триватиме одна епоха на повному наборі."""
import json
import os
import time
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import tensorflow as tf  # noqa: E402
from tensorflow.keras.preprocessing.image import ImageDataGenerator  # noqa: E402

LAB_ROOT = Path(__file__).resolve().parent.parent
BASE = LAB_ROOT / "data" / "cats_dogs"
PROBE_STEPS = 60
BATCH = 32

datagen = ImageDataGenerator(rescale=1. / 255)
train_gen = datagen.flow_from_directory(str(BASE / "train"), target_size=(150, 150),
                                        batch_size=BATCH, class_mode="binary")
val_gen = datagen.flow_from_directory(str(BASE / "val"), target_size=(150, 150),
                                      batch_size=BATCH, class_mode="binary")

model = tf.keras.Sequential([
    tf.keras.layers.Conv2D(32, (3, 3), input_shape=(150, 150, 3)), tf.keras.layers.Activation("relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(32, (3, 3)), tf.keras.layers.Activation("relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(64, (3, 3)), tf.keras.layers.Activation("relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Flatten(), tf.keras.layers.Dense(64), tf.keras.layers.Activation("relu"),
    tf.keras.layers.Dropout(0.5), tf.keras.layers.Dense(1), tf.keras.layers.Activation("sigmoid"),
])
model.compile(loss="binary_crossentropy", optimizer="adam", metrics=["accuracy"])

t0 = time.time()
model.fit(train_gen, steps_per_epoch=PROBE_STEPS, epochs=1, verbose=2)
probe_sec = time.time() - t0

t0 = time.time()
model.evaluate(val_gen, steps=20, verbose=0)
val_step_sec = (time.time() - t0) / 20

full_steps = train_gen.samples // BATCH
val_steps = val_gen.samples // BATCH
per_step = probe_sec / PROBE_STEPS
full_epoch = per_step * full_steps + val_step_sec * val_steps

out = {
    "cpu_only": not tf.config.list_physical_devices("GPU"),
    "probe_steps": PROBE_STEPS,
    "probe_sec": round(probe_sec, 1),
    "sec_per_train_step": round(per_step, 3),
    "sec_per_val_step": round(val_step_sec, 3),
    "full_train_steps": full_steps,
    "full_val_steps": val_steps,
    "projected_full_epoch_sec": round(full_epoch, 1),
    "projected_full_epoch_min": round(full_epoch / 60, 1),
    "subset_2000_epoch_min": round((per_step * (2000 * 2 // BATCH) + val_step_sec * (500 * 2 // BATCH)) / 60, 1),
}
print(json.dumps(out, indent=2))
(LAB_ROOT / "results" / "raw" / "timing_probe.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
