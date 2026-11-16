r"""Клітинки ноутбука 04 — оцінка, інтерпретація, тестування на невідомих даних.

Усе, чого умова вимагає від розділу оцінювання: матриця помилок, precision,
recall, F1, аналіз помилок, і перевірка на зображеннях, яких модель не бачила
ні під час навчання, ні під час підбору гіперпараметрів.
"""

LOAD_BEST = r'''# Pick the best model straight from the registry on Drive: the notebook does not
# need to be told which experiment won, and it stays correct if 03 is re-run.
RUNS_DIR = DRIVE_DIR / 'runs'
MODELS_DIR = DRIVE_DIR / 'models'
results = {f.stem: json.loads(f.read_text(encoding='utf-8'))
           for f in sorted(RUNS_DIR.glob('*.json'))}
if not results:
    raise RuntimeError(f'у {RUNS_DIR} немає жодного прогону — виконайте ноутбуки 02 і 03')

DISPLAY = CLASSES.get('display', {})


def label(class_dir):
    return DISPLAY.get(class_dir, class_dir.replace('_', ' '))


# The winner is chosen by VALIDATION accuracy, never by test accuracy.
# Picking the model that scores best on the test set turns that set into part of
# the fitting procedure, and the number it then reports is optimistically biased.
# Per-run test accuracy is still printed in the final table for completeness,
# but nothing in the project selects on it.
top15_runs = [n for n in results if results[n]['n_classes'] == len(TOP15)]
BEST = max(top15_runs, key=lambda n: results[n]['best_val_accuracy'])
BEST_REC = results[BEST]

_by_test = max(top15_runs, key=lambda n: results[n]['test_accuracy'])
if _by_test != BEST:
    print(f'за тестовою вибіркою кращим виглядав би {_by_test} '
          f"(test {results[_by_test]['test_accuracy']:.4f}), але вибір за нею "
          'зіпсував би оцінку — беремо найкращу за перевірочною\n')
ACTIVE_CLASSES = TOP15
IMG_SIZE = BEST_REC['config'].get('img_size', 224)
BATCH = 32

print(f'найкраща модель: {BEST} — {BEST_REC["title"]}')
print(f"  val {BEST_REC['best_val_accuracy']:.4f} | test {BEST_REC['test_accuracy']:.4f}"
      f" | вхід {IMG_SIZE}x{IMG_SIZE} | {BEST_REC['params']:,} параметрів")

model = keras.models.load_model(MODELS_DIR / f'{BEST}.keras')
print('модель завантажено')'''


PREDICT = r'''# Predictions on the held-out test subset. These images were set aside in
# notebook 01 and were never used for training, early stopping or tuning.
# shuffle=False keeps the order aligned with file_paths.
raw_test = keras.utils.image_dataset_from_directory(
    DATA_DIR / 'test', labels='inferred', label_mode='int',
    class_names=ACTIVE_CLASSES, image_size=(IMG_SIZE, IMG_SIZE),
    batch_size=BATCH, shuffle=False, interpolation='bilinear', verbose=False)
FILE_PATHS = [Path(p) for p in raw_test.file_paths]

y_true = np.concatenate([y.numpy() for _, y in raw_test])
probs = model.predict(raw_test.prefetch(tf.data.AUTOTUNE), verbose=1)
y_pred = probs.argmax(axis=1)

print(f'\nтестових зображень: {len(y_true)} у {len(ACTIVE_CLASSES)} класах')
print('правильно:', int((y_pred == y_true).sum()))'''


METRICS = r'''# The metrics the task asks for, each computed per class and then averaged.
#
# Accuracy alone is misleading on an imbalanced set: a model that always answers
# "van Gogh" would already look respectable. Macro averaging gives every artist
# the same weight regardless of how many paintings they have, so the macro F1
# below is the honest headline number.
from sklearn.metrics import (classification_report, confusion_matrix,
                             precision_recall_fscore_support)

accuracy = float((y_pred == y_true).mean())
top3 = float(np.mean([y in row for y, row in
                      zip(y_true, np.argsort(probs, axis=1)[:, -3:])]))

macro = precision_recall_fscore_support(y_true, y_pred, average='macro', zero_division=0)
weighted = precision_recall_fscore_support(y_true, y_pred, average='weighted', zero_division=0)

print(f'accuracy        : {accuracy:.4f}')
print(f'top-3 accuracy  : {top3:.4f}')
print(f'macro    precision {macro[0]:.4f} | recall {macro[1]:.4f} | F1 {macro[2]:.4f}')
print(f'weighted precision {weighted[0]:.4f} | recall {weighted[1]:.4f} | F1 {weighted[2]:.4f}')

report = classification_report(y_true, y_pred,
                               target_names=[label(c) for c in ACTIVE_CLASSES],
                               digits=3, zero_division=0, output_dict=True)
report_df = pd.DataFrame(report).T.round(3)
print('\n' + report_df.to_string())
report_df.to_csv(RESULTS / 'raw' / 'nb04_classification_report.csv', encoding='utf-8')'''


CONFUSION = r'''# Confusion matrix twice: raw counts, and normalised by row so that classes of
# very different size can be compared at all.
cm = confusion_matrix(y_true, y_pred, labels=range(len(ACTIVE_CLASSES)))
cm_norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
names = [label(c) for c in ACTIVE_CLASSES]

# Висота підібрана так, щоб кожна панель лишалась приблизно квадратною:
# imshow тримає співвідношення сторін, і зайва висота стає порожнечею.
fig, axes = plt.subplots(1, 2, figsize=(4 + 0.72 * len(names),
                                        2.6 + 0.36 * len(names)))
for ax, data, title, fmt in ((axes[0], cm, 'кількість', '{:d}'),
                             (axes[1], cm_norm, 'частка від класу', '{:.2f}')):
    im = ax.imshow(data, cmap='Blues')
    ax.set_xticks(range(len(names)))
    ax.set_yticks(range(len(names)))
    ax.set_xticklabels(names, rotation=90, fontsize=7)
    ax.set_yticklabels(names, fontsize=7)
    ax.set_xlabel('прогноз')
    ax.set_ylabel('насправді')
    ax.set_title(title, fontsize=11)
    if len(names) <= 20:
        threshold = data.max() / 2
        for i in range(len(names)):
            for j in range(len(names)):
                if data[i, j]:
                    ax.text(j, i, fmt.format(data[i, j]), ha='center', va='center',
                            fontsize=6,
                            color='white' if data[i, j] > threshold else 'black')
    fig.colorbar(im, ax=ax, fraction=0.046)
fig.suptitle(f'Матриця помилок — {BEST} (test accuracy {accuracy:.3f})', fontsize=13)
plt.tight_layout()
plt.savefig(RESULTS / 'nb04_confusion_matrix.png', dpi=110, bbox_inches='tight')
plt.show()

pairs = [(names[i], names[j], int(cm[i, j]), float(cm_norm[i, j]))
         for i in range(len(names)) for j in range(len(names))
         if i != j and cm[i, j]]
pairs.sort(key=lambda t: t[2], reverse=True)
confused = pd.DataFrame(pairs[:12], columns=['насправді', 'прогноз',
                                             'випадків', 'частка класу'])
print('найчастіші плутанини:')
print(confused.to_string(index=False))'''


PERCLASS = r'''# Per-class F1 against class size: the picture of what imbalance actually did.
support = cm.sum(axis=1)
per_class = precision_recall_fscore_support(y_true, y_pred,
                                            labels=range(len(ACTIVE_CLASSES)),
                                            zero_division=0)
order = np.argsort(per_class[2])

fig, axes = plt.subplots(1, 2, figsize=(13, 0.4 * len(names) + 2.5))
axes[0].barh([names[i] for i in order], per_class[2][order], color='royalblue')
axes[0].axvline(macro[2], color='crimson', ls='--', label=f'macro F1 {macro[2]:.3f}')
axes[0].set_xlabel('F1')
axes[0].set_xlim(0, 1)
axes[0].set_title('F1 за класами')
axes[0].legend(fontsize=8)
axes[1].scatter(support, per_class[2], color='royalblue')
for i, name in enumerate(names):
    axes[1].annotate(name, (support[i], per_class[2][i]), fontsize=6,
                     xytext=(3, 3), textcoords='offset points')
axes[1].set_xlabel('зображень у тестовій вибірці')
axes[1].set_ylabel('F1')
axes[1].set_title('F1 проти розміру класу')
for ax in axes:
    ax.grid(alpha=0.3)
fig.suptitle('Якість за класами', fontsize=13)
plt.tight_layout()
plt.savefig(RESULTS / 'nb04_per_class_f1.png', dpi=110, bbox_inches='tight')
plt.show()

print(f'кореляція між розміром класу і F1: '
      f'{np.corrcoef(support, per_class[2])[0, 1]:.3f}')'''


ERRORS = r'''# The mistakes themselves, sorted by how confident the model was while wrong.
# A confident error says something different about a model than a hesitant one.
from PIL import Image

wrong = np.where(y_pred != y_true)[0]
confidence = probs[np.arange(len(y_pred)), y_pred]
wrong = wrong[np.argsort(-confidence[wrong])]
print(f'помилок: {len(wrong)} з {len(y_true)}')

show = wrong[:12]
if len(show):
    cols = 4
    rows = -(-len(show) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(3.2 * cols, 3.6 * rows),
                             squeeze=False)
    for ax, idx in zip(axes.ravel(), show):
        with Image.open(FILE_PATHS[idx]) as im:
            ax.imshow(im.convert('RGB'))
        ax.set_title(f'це {names[y_true[idx]]}\nмодель: {names[y_pred[idx]]} '
                     f'({confidence[idx]:.2f})', fontsize=8, color='crimson')
        ax.axis('off')
    for ax in axes.ravel()[len(show):]:
        ax.axis('off')
    fig.suptitle('Найвпевненіші помилки на тестовій вибірці', fontsize=13)
    plt.tight_layout(rect=(0, 0, 1, 0.98))
    plt.savefig(RESULTS / 'nb04_errors.png', dpi=110, bbox_inches='tight')
    plt.show()

print(f'середня впевненість: правильні {confidence[y_pred == y_true].mean():.3f}, '
      f'помилкові {confidence[y_pred != y_true].mean():.3f}')'''


GRADCAM = r'''# Grad-CAM: where in the painting the decision came from.
#
# Gradients of the predicted class are taken with respect to the last feature map
# and used to weight its channels. The model is split into three parts instead of
# building a second Model over an internal tensor, because a pretrained backbone
# is a nested model and its internal tensors do not belong to the outer graph.
#
# Reference: Selvaraju et al., "Grad-CAM: Visual Explanations from Deep Networks
# via Gradient-based Localization", ICCV 2017, arXiv:1610.02391.
def split_for_gradcam(model):
    layers = [l for l in model.layers
              if not isinstance(l, keras.layers.InputLayer)]
    for i, l in enumerate(layers):
        if isinstance(l, keras.Model) and not isinstance(l, keras.Sequential):
            return layers[:i], l, layers[i + 1:]
    convs = [i for i, l in enumerate(layers) if isinstance(l, keras.layers.Conv2D)]
    if not convs:
        raise LookupError('у моделі немає згорткових шарів')
    i = convs[-1]
    return layers[:i + 1], layers[i], layers[i + 1:]


PRE_LAYERS, FEAT_LAYER, POST_LAYERS = split_for_gradcam(model)
if isinstance(FEAT_LAYER, keras.layers.Conv2D):
    PRE_LAYERS = PRE_LAYERS[:-1]
print('шари до ознак:', [l.name for l in PRE_LAYERS])
print('шар ознак    :', FEAT_LAYER.name)
print('шари після   :', [l.name for l in POST_LAYERS])


def grad_cam(image_batch, class_idx):
    x = tf.convert_to_tensor(image_batch, dtype=tf.float32)
    with tf.GradientTape() as tape:
        for layer in PRE_LAYERS:
            x = layer(x, training=False)
        features = FEAT_LAYER(x, training=False)
        tape.watch(features)
        y = features
        for layer in POST_LAYERS:
            y = layer(y, training=False)
        score = y[:, class_idx]
    grads = tape.gradient(score, features)
    weights = tf.reduce_mean(grads, axis=(1, 2))
    cam = tf.reduce_sum(features * weights[:, None, None, :], axis=-1)
    cam = tf.nn.relu(cam)[0]
    cam = cam / (tf.reduce_max(cam) + 1e-8)
    return cam.numpy()


def pick_diverse(indices, limit=6):
    """По одному прикладу на клас.

    Просто взяти шістку найвпевненіших марно: вони майже завжди належать
    одному-двом художникам, і сітка нічого не показує про решту.
    """
    seen, picked = set(), []
    for i in indices:
        class_idx = int(y_true[i])
        if class_idx in seen:
            continue
        seen.add(class_idx)
        picked.append(i)
        if len(picked) >= limit:
            break
    return picked


def show_gradcam(indices, fname, suptitle):
    indices = pick_diverse(indices)
    if not indices:
        print('немає прикладів для', suptitle)
        return
    fig, axes = plt.subplots(2, len(indices), figsize=(2.9 * len(indices), 6.8),
                             squeeze=False)
    for col, idx in enumerate(indices):
        array = keras.utils.img_to_array(
            keras.utils.load_img(FILE_PATHS[idx], target_size=(IMG_SIZE, IMG_SIZE)))
        cam = grad_cam(array[None, ...], int(y_pred[idx]))
        axes[0][col].imshow(array.astype('uint8'))
        axes[0][col].set_title(f'{names[y_true[idx]]}', fontsize=8)
        axes[1][col].imshow(array.astype('uint8'))
        # Карта ознак EfficientNetB0 на вході 224 має розмір 7x7, тож без
        # згладжування поверх картини лягає шахівниця з 49 квадратів.
        axes[1][col].imshow(cam, cmap='jet', alpha=0.45,
                            extent=(0, IMG_SIZE, IMG_SIZE, 0),
                            interpolation='bilinear')
        ok = y_pred[idx] == y_true[idx]
        axes[1][col].set_title(f'{names[y_pred[idx]]} ({confidence[idx]:.2f})',
                               fontsize=8, color='seagreen' if ok else 'crimson')
        for row in (0, 1):
            axes[row][col].axis('off')
    fig.suptitle(suptitle, fontsize=13)
    plt.tight_layout(h_pad=2.4)
    plt.savefig(RESULTS / fname, dpi=110, bbox_inches='tight')
    plt.show()


right = np.where(y_pred == y_true)[0]
show_gradcam(right[np.argsort(-confidence[right])], 'nb04_gradcam_correct.png',
             'Grad-CAM: упевнені правильні відповіді')
show_gradcam(wrong, 'nb04_gradcam_wrong.png',
             'Grad-CAM: упевнені помилки')'''


EXTERNAL = r'''# Paintings the model has never seen in any form: not in train, not in val,
# not in test, not in the Kaggle dataset at all. Files live in
# my_images/<Artist_Folder>/, so the expected answer comes from the folder name.
MY_IMAGES = (Path('/content/my_images') if IN_COLAB
             else PROJECT_ROOT / 'my_images')

if IN_COLAB and not MY_IMAGES.exists():
    src = DRIVE_DIR / 'my_images.zip'
    if src.exists():
        with zipfile.ZipFile(src) as z:
            z.extractall(MY_IMAGES)
    else:
        print(f'немає {src} — запустіть scripts/fetch_test_images.py і залийте '
              'my_images.zip на Drive')

external = sorted(p for p in MY_IMAGES.rglob('*.jpg')
                  if p.parent.name in ACTIVE_CLASSES)
print(f'зовнішніх зображень: {len(external)}')

if external:
    batch = np.stack([keras.utils.img_to_array(
        keras.utils.load_img(p, target_size=(IMG_SIZE, IMG_SIZE))) for p in external])
    ext_probs = model.predict(batch, verbose=0)
    ext_pred = ext_probs.argmax(axis=1)
    ext_true = np.array([ACTIVE_CLASSES.index(p.parent.name) for p in external])
    ext_conf = ext_probs[np.arange(len(ext_pred)), ext_pred]
    ext_top3 = float(np.mean([y in row for y, row in
                              zip(ext_true, np.argsort(ext_probs, axis=1)[:, -3:])]))
    ext_acc = float((ext_pred == ext_true).mean())

    print(f'точність на зовнішніх зображеннях: {ext_acc:.3f} '
          f'({int((ext_pred == ext_true).sum())} з {len(ext_true)}), top-3 {ext_top3:.3f}')
    print(f'на тестовій вибірці того самого набору: {accuracy:.3f}')

    ext_table = pd.DataFrame({
        'файл': [p.name for p in external],
        'насправді': [label(p.parent.name) for p in external],
        'прогноз': [names[i] for i in ext_pred],
        'впевненість': ext_conf.round(3),
        'вгадано': ext_pred == ext_true,
    })
    print('\n' + ext_table.to_string(index=False))
    ext_table.to_csv(RESULTS / 'raw' / 'nb04_external.csv', index=False, encoding='utf-8')

    cols = min(5, len(external))
    rows = -(-len(external) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(3.1 * cols, 3.6 * rows), squeeze=False)
    for ax, i in zip(axes.ravel(), range(len(external))):
        ax.imshow(batch[i].astype('uint8'))
        ok = ext_pred[i] == ext_true[i]
        ax.set_title(f'{label(external[i].parent.name)}\n-> {names[ext_pred[i]]} '
                     f'({ext_conf[i]:.2f})', fontsize=8,
                     color='seagreen' if ok else 'crimson')
        ax.axis('off')
    for ax in axes.ravel()[len(external):]:
        ax.axis('off')
    fig.suptitle('Картини, яких модель не бачила ніколи', fontsize=13)
    # rect лишає смугу під suptitle: інакше на високій сітці він налазить
    # на підписи верхнього ряду.
    plt.tight_layout(rect=(0, 0, 1, 0.98))
    plt.savefig(RESULTS / 'nb04_external_images.png', dpi=110, bbox_inches='tight')
    plt.show()
else:
    ext_acc = ext_top3 = None
    print('зовнішніх зображень немає — розділ пропущено')'''


UPLOAD = r'''# Optional: try the model on a file picked by hand, right here.
if IN_COLAB:
    from google.colab import files

    print('оберіть зображення (або натисніть Скасувати, щоб пропустити)')
    uploaded = files.upload()
    for filename in uploaded:
        array = keras.utils.img_to_array(
            keras.utils.load_img(filename, target_size=(IMG_SIZE, IMG_SIZE)))
        p = model.predict(array[None, ...], verbose=0)[0]
        order = np.argsort(-p)[:3]
        plt.figure(figsize=(3.4, 3.4))
        plt.imshow(array.astype('uint8'))
        plt.axis('off')
        plt.title(filename, fontsize=9)
        plt.show()
        for rank, i in enumerate(order, 1):
            print(f'  {rank}. {names[i]:<28} {p[i]:.3f}')
else:
    print('клітинка працює лише в Colab')'''


COMPARE = r'''# Final comparison of every experiment in the project, in one table.
def frame(names_):
    rows = []
    for name in names_:
        r = results[name]
        rows.append({'експеримент': name, 'опис': r['title'], 'класів': r['n_classes'],
                     'параметрів': r['params'], 'епох': r['epochs_run'],
                     'val acc': round(r['best_val_accuracy'], 4),
                     'test acc': round(r['test_accuracy'], 4),
                     'test top-3': round(r['test_top3_accuracy'], 4),
                     'розрив': round(r['overfit_gap'], 4),
                     'хв': round(r['seconds'] / 60, 1)})
    return pd.DataFrame(rows).sort_values('test acc', ascending=False).reset_index(drop=True)


final = frame(list(results))
print(final.to_string(index=False))
final.to_csv(RESULTS / 'raw' / 'nb04_all_experiments.csv', index=False, encoding='utf-8')

fig, ax = plt.subplots(figsize=(9, 0.42 * len(final) + 2))
subset = final[final['класів'] == len(ACTIVE_CLASSES)].iloc[::-1]
colors = ['seagreen' if n.startswith('b') else 'royalblue' for n in subset['експеримент']]
ax.barh(subset['експеримент'], subset['test acc'], color=colors)
ax.set_xlabel('точність на тестовій вибірці')
ax.set_xlim(0, 1)
ax.grid(axis='x', alpha=0.3)
ax.set_title(f'Усі експерименти на треку top-15 '
             f'(синій — з нуля, зелений — перенесення навчання)', fontsize=11)
for i, v in enumerate(subset['test acc']):
    ax.text(v + 0.01, i, f'{v:.3f}', va='center', fontsize=7)
plt.tight_layout()
plt.savefig(RESULTS / 'nb04_all_experiments.png', dpi=110, bbox_inches='tight')
plt.show()'''


EXPORT_04 = r'''# Everything the evaluation section of the report needs, in one JSON.
payload = {
    'notebook': 'nb04',
    'best_model': BEST,
    'best_title': BEST_REC['title'],
    'n_classes': len(ACTIVE_CLASSES),
    'classes': [label(c) for c in ACTIVE_CLASSES],
    'test_accuracy': accuracy,
    'test_top3_accuracy': top3,
    'macro': {'precision': float(macro[0]), 'recall': float(macro[1]),
              'f1': float(macro[2])},
    'weighted': {'precision': float(weighted[0]), 'recall': float(weighted[1]),
                 'f1': float(weighted[2])},
    'per_class_f1': {label(c): float(v) for c, v in zip(ACTIVE_CLASSES, per_class[2])},
    'support': {label(c): int(v) for c, v in zip(ACTIVE_CLASSES, support)},
    'confusion_matrix': cm.tolist(),
    'most_confused': confused.to_dict('records'),
    'n_errors': int(len(wrong)),
    'mean_confidence_correct': float(confidence[y_pred == y_true].mean()),
    'mean_confidence_wrong': float(confidence[y_pred != y_true].mean())
                             if len(wrong) else None,
    'external_accuracy': ext_acc,
    'external_top3_accuracy': ext_top3,
    'all_runs': {k: {kk: vv for kk, vv in v.items() if kk != 'history'}
                 for k, v in results.items()},
}
out = RESULTS / 'raw' / 'nb04.json'
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
print('записано', out)

zip_path = PROJECT_ROOT / 'project_nb04_results.zip'
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted(RESULTS.rglob('*')):
        if f.is_file() and f.suffix in ('.json', '.png', '.csv', '.md'):
            z.write(f, f.relative_to(RESULTS))
print('зіп:', zip_path, f'({zip_path.stat().st_size / 1e6:.1f} МБ)')

if IN_COLAB:
    from google.colab import files

    files.download(str(zip_path))'''
