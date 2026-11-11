# Навчені моделі лабораторної 8

**Пункт 6** умови: «Зберегти ці 3-4 або більше моделей мережі, які ви навчили
в репозиторій (**або в файли на диск**)». Обрано другий варіант.

Чому не в репозиторій: чотири донавчені моделі разом важать приблизно 250 МБ, а
правило `*.keras` в `.gitignore` монорепозиторію діє ще з лабораторної 7. Тому
самі файли лежать на диску й на Google Drive, а тут — їхній опис із контрольними
сумами, щоб кожну модель можна було звірити й відтворити.

## Де лежать файли

| Місце | Шлях |
|---|---|
| Google Drive (основна копія) | `MyDrive/dl_lab8/models/` |
| Локально після завантаження | `dl/lab8/models/` (у `.gitignore`) |
| У Colab під час прогону | `/content/models/` |

## Моделі

Таблиця заповнюється після прогону ноутбуків — числа беруться з
`results/metrics.json` (поле `model` кожної мережі) і не вписуються руками.

| Мережа | Файл | Розмір | sha256 | test accuracy | Dropout |
|---|---|---|---|---|---|
| VGG16 | `lab8_vgg16_finetuned.keras` | — | — | — | — |
| InceptionV3 | `lab8_inception_v3_finetuned.keras` | — | — | — | — |
| ResNet50 | `lab8_resnet50_finetuned.keras` | — | — | — | — |
| MobileNetV2 | `lab8_mobilenet_v2_finetuned.keras` | — | — | — | — |

Кожен ноутбук додатково зберігає проміжну модель етапу B
(`lab8_<мережа>_frozen.keras`) — її залишає `ModelCheckpoint` за найкращим
`val_loss`. Для звіту вона не потрібна, але лишається на Drive.

## Як завантажити модель

```python
from tensorflow import keras
from tensorflow.keras.applications.vgg16 import preprocess_input
from tensorflow.keras.utils import img_to_array, load_img
import numpy as np

model = keras.models.load_model("lab8_vgg16_finetuned.keras")

x = img_to_array(load_img("cat.jpg", target_size=(224, 224)))
prob = float(model.predict(preprocess_input(np.expand_dims(x, 0)))[0][0])
print("dog" if prob > 0.5 else "cat", prob)
```

Два важливі моменти:

- **вхід 224×224** для всіх чотирьох моделей;
- **`preprocess_input` саме своєї мережі** — у VGG16, ResNet50, InceptionV3 і
  MobileNetV2 вони різні, і `rescale=1./255` з лабораторної 7 не підходить.
  Класи: `0 = cat`, `1 = dog`.

## Як відтворити

```powershell
cd c:\uni_year_4\dl\lab8
$env:PYTHONUTF8 = "1"
..\lab7\.venv\Scripts\python.exe scripts\make_notebooks.py
```

Далі — за `TUTORIAL.md`: ноутбуки виконуються в Google Colab на GPU, кожен
наприкінці зберігає свою модель.
