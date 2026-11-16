r"""Клітинки ноутбука 05 — рідкісні художники.

Окремий ноутбук під одне питання: чи можна розпізнавати художників, яких у
наборі лишилося по два-три десятки картин. Перевіряються два різні шляхи:

* **розподілом** — ваги, функція втрат, семплювання, перенавчання лише
  класифікатора, поправка на апріорні ймовірності, прототипи без навчання;
* **поглядом на полотно** — вирізки у власному масштабі, перемішування робіт
  художника між собою, і вибір масштабу окремо для кожного класу.

Жодного зображення ззовні: умова прив'язує роботу до цього набору, тож усе
робиться з тих самих 8435 картин. Міра теж одна — повнота на смузі рідкісних
класів, а не загальна точність, яку численні класи й так витягують.
"""

# --------------------------------------------------- смуги класів і допоміжне
BANDS = r'''# Classes are split into bands by how many training images they have: a single
# accuracy number cannot show what imbalance does, because the seven largest
# classes alone hold more than half of the training set.
#
# The tail threshold is not arbitrary. 60 images is under two mini-batches of
# 32, i.e. a class that contributes roughly one gradient step per epoch.
from sklearn.metrics import f1_score, precision_recall_fscore_support

# Folder name -> the artist's name as artists.csv spells it (notebook 01 wrote
# this mapping, which is what repaired the two mojibake Duerer folders).
DISPLAY = CLASSES.get('display', {})


def label(class_dir):
    return DISPLAY.get(class_dir, class_dir.replace('_', ' '))


TRAIN_COUNTS = {c: len(list((DATA_DIR / 'train' / c).glob('*.jpg'))) for c in ALL50}
HEAD_MIN, TAIL_MAX = 200, 60
BAND_NAMES = ('head', 'mid', 'tail')
BAND_TITLE = {'head': 'численні', 'mid': 'середні', 'tail': 'рідкісні'}


def band_of(class_dir):
    n = TRAIN_COUNTS[class_dir]
    if n >= HEAD_MIN:
        return 'head'
    return 'tail' if n < TAIL_MAX else 'mid'


BANDS_OF = {b: [c for c in ALL50 if band_of(c) == b] for b in BAND_NAMES}
TAIL = BANDS_OF['tail']
TOTAL_TRAIN = max(sum(TRAIN_COUNTS.values()), 1)

for _band in BAND_NAMES:
    _members = BANDS_OF[_band]
    _total = sum(TRAIN_COUNTS[c] for c in _members)
    print(f'{BAND_TITLE[_band]:<10} {len(_members):>2} класів, {_total:>5} зображень '
          f'({_total / TOTAL_TRAIN:.0%} навчальної вибірки)')
print('\nрідкісні класи:')
for _c in sorted(TAIL, key=lambda c: TRAIN_COUNTS[c]):
    print(f'  {label(_c):<28}{TRAIN_COUNTS[_c]:>4} у навчальній вибірці')


def file_label_list(class_names, split='train'):
    """Files and labels in a fixed order, for the pipelines built by hand below."""
    paths, labels = [], []
    for index, class_dir in enumerate(class_names):
        for path in sorted((DATA_DIR / split / class_dir).glob('*.jpg')):
            paths.append(str(path))
            labels.append(index)
    return paths, labels


def decode_square(path, size):
    """Same as image_dataset_from_directory: float32 in [0, 255], squashed."""
    image = tf.io.decode_jpeg(tf.io.read_file(path), channels=3)
    return tf.image.resize(tf.cast(image, tf.float32), (size, size), method='bilinear')


def decode_short_side(path, short):
    """Keep the aspect ratio and scale the short side — for crops."""
    image = tf.cast(tf.io.decode_jpeg(tf.io.read_file(path), channels=3), tf.float32)
    shape = tf.cast(tf.shape(image)[:2], tf.float32)
    size = tf.cast(tf.round(shape * (short / tf.reduce_min(shape))), tf.int32)
    return tf.image.resize(image, size, method='bilinear')'''


# ------------------------------------------------------- спільне вимірювання
MEASURE = r'''# One place where every method is measured, so that a trained model, a post-hoc
# correction and a nearest-centroid classifier land in the same table.
#
# The headline number here is NOT accuracy: it is the mean per-class recall on
# the tail band. Accuracy on this set is decided by van Gogh and Degas.
TAIL_DIR = DRIVE_DIR / 'tail'
TAIL_DIR.mkdir(parents=True, exist_ok=True)
tail_metrics = {}
for _f in sorted(TAIL_DIR.glob('*.json')):
    tail_metrics[_f.stem] = json.loads(_f.read_text(encoding='utf-8'))
print(f'уже виміряно методів: {len(tail_metrics)}')


def split_dataset(split, img_size=224, batch=32):
    return keras.utils.image_dataset_from_directory(
        DATA_DIR / split, labels='inferred', label_mode='int', class_names=ALL50,
        image_size=(img_size, img_size), batch_size=batch, shuffle=False,
        interpolation='bilinear', verbose=False).prefetch(AUTOTUNE)


def true_labels(split, img_size=224):
    ds = keras.utils.image_dataset_from_directory(
        DATA_DIR / split, labels='inferred', label_mode='int', class_names=ALL50,
        image_size=(img_size, img_size), batch_size=32, shuffle=False,
        interpolation='bilinear', verbose=False)
    return np.concatenate([y.numpy() for _, y in ds])


# Built from the original tree, and deliberately never rebuilt: runs that train
# on topped-up data must still be measured on exactly these images.
TEST_DS, Y_TEST = split_dataset('test'), true_labels('test')
VAL_DS, Y_VAL = split_dataset('val'), true_labels('val')
print(f'тестова {len(Y_TEST)}, перевірочна {len(Y_VAL)} зображень '
      f'у {len(ALL50)} класах')


def band_mean(per_class, band):
    members = BANDS_OF[band]
    if not members:
        return float('nan')
    return float(np.nanmean([per_class[c] for c in members]))


def record_tail(name, title, scores, y_true, kind='навчання', store=True):
    """Measure one method. `scores` may be probabilities or logits.

    store=False computes and prints the numbers without putting them in the
    registry — for sweeps whose points are a curve, not competing methods.
    """
    y_pred = scores.argmax(axis=1)
    stats = precision_recall_fscore_support(y_true, y_pred,
                                            labels=range(len(ALL50)), zero_division=0)
    recall, f1 = {}, {}
    for i, class_dir in enumerate(ALL50):
        seen = int((y_true == i).sum())
        recall[class_dir] = float(stats[1][i]) if seen else float('nan')
        f1[class_dir] = float(stats[2][i]) if seen else float('nan')

    order = np.argsort(scores, axis=1)[:, -3:]
    metrics = {
        'name': name, 'title': title, 'kind': kind,
        'accuracy': float((y_pred == y_true).mean()),
        'balanced_accuracy': float(np.nanmean(list(recall.values()))),
        'macro_f1': float(f1_score(y_true, y_pred, average='macro', zero_division=0)),
        'top3_accuracy': float(np.mean([t in row for t, row in zip(y_true, order)])),
        'recall': recall, 'f1': f1,
        'band_recall': {b: band_mean(recall, b) for b in BAND_NAMES},
    }
    if store:
        tail_metrics[name] = metrics
        (TAIL_DIR / f'{name}.json').write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    bands = metrics['band_recall']
    print(f"[{name}] accuracy {metrics['accuracy']:.4f} | збалансована "
          f"{metrics['balanced_accuracy']:.4f} | повнота: численні {bands['head']:.3f}, "
          f"середні {bands['mid']:.3f}, РІДКІСНІ {bands['tail']:.3f}")
    return metrics


def evaluate_saved(name, title=None, scores=None, kind='навчання'):
    """Measure a saved model; predictions may be passed in ready-made."""
    if name in tail_metrics and not FORCE_RERUN:
        print(f'[{name}] уже виміряно — пропускаю')
        return tail_metrics[name]
    if title is None:
        title = results.get(name, {}).get('title', name)
    if scores is None:
        # compile=False: some models are trained with a custom loss, and loading
        # them compiled would need custom_objects.
        model = keras.models.load_model(MODELS_DIR / f'{name}.keras', compile=False)
        scores = model.predict(TEST_DS, verbose=0)
        del model
        keras.backend.clear_session()
    return record_tail(name, title, scores, Y_TEST, kind=kind)'''


# ------------------------------------------------------------ опорна модель
REFERENCE = r'''# The starting point: the all-50 model already trained in notebook 03. Nothing
# is trained here — this is the measurement everything else is compared against.
ALL50_RUNS = [n for n in results if results[n]['n_classes'] == len(ALL50)]
if not ALL50_RUNS:
    raise RuntimeError('немає прогонів на 50 класах — спочатку виконайте ноутбук 03')

REF = max(ALL50_RUNS, key=lambda n: results[n]['best_val_accuracy'])
print(f'опорна модель: {REF} — {results[REF]["title"]}\n')
ref_metrics = evaluate_saved(REF, kind='опорна')

ref_frame = pd.DataFrame([
    {'художник': label(c), 'у навчальній': TRAIN_COUNTS[c],
     'смуга': BAND_TITLE[band_of(c)],
     'повнота': round(ref_metrics['recall'][c], 3),
     'F1': round(ref_metrics['f1'][c], 3)} for c in ALL50])
print('\nдесять найгірших класів опорної моделі:')
print(ref_frame.sort_values('повнота').head(10).to_string(index=False))

_zero = ref_frame.loc[ref_frame['повнота'] == 0, 'художник'].tolist()
print(f'\nкласів, де модель не вгадала жодної картини: {len(_zero)}'
      + (' — ' + ', '.join(_zero) if _zero else ''))
_bands = ref_metrics['band_recall']
print(f"розрив повноти між численними й рідкісними: "
      f"{_bands['head'] - _bands['tail']:+.3f}")'''


# ------------------------------------- чи виразніші рідкісні художники (гіпотеза)
EMBED = r'''# The hypothesis to test before trying to fix anything: that rare artists are
# stylistically more distinctive, and so need fewer examples than their size
# suggests. Testing it with the classifier would be circular, so distinctiveness
# is measured in a feature space that never saw these labels: plain ImageNet
# EfficientNetB0 embeddings.
#
# margin = (how close a class's own paintings sit to its centroid)
#        - (how close that centroid sits to the nearest other centroid)
# A large margin means the class is compact and far from everything else.
from scipy.stats import spearmanr

EMB_SIZE = 224
emb_model = keras.applications.EfficientNetB0(
    include_top=False, weights='imagenet', pooling='avg',
    input_shape=(EMB_SIZE, EMB_SIZE, 3))


def embed(paths, batch=32):
    ds = (tf.data.Dataset.from_tensor_slices(paths)
          .map(lambda p: decode_square(p, EMB_SIZE), num_parallel_calls=AUTOTUNE)
          .batch(batch).prefetch(AUTOTUNE))
    vectors = emb_model.predict(ds, verbose=0)
    return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)


TRAIN_PATHS, TRAIN_LABELS = file_label_list(ALL50, 'train')
TRAIN_LABELS = np.array(TRAIN_LABELS)
print(f'ознаки для {len(TRAIN_PATHS)} навчальних зображень...')
E_TRAIN = embed(TRAIN_PATHS)

CENTROIDS = np.stack([E_TRAIN[TRAIN_LABELS == i].mean(axis=0)
                      for i in range(len(ALL50))])
CENTROIDS /= np.maximum(np.linalg.norm(CENTROIDS, axis=1, keepdims=True), 1e-9)

intra = np.array([float((E_TRAIN[TRAIN_LABELS == i] @ CENTROIDS[i]).mean())
                  for i in range(len(ALL50))])
similarity = CENTROIDS @ CENTROIDS.T
np.fill_diagonal(similarity, -1.0)
inter = similarity.max(axis=1)
margin = intra - inter

distinct = pd.DataFrame({
    'художник': [label(c) for c in ALL50],
    'клас': ALL50,
    'у навчальній': [TRAIN_COUNTS[c] for c in ALL50],
    'смуга': [BAND_TITLE[band_of(c)] for c in ALL50],
    'компактність': intra.round(3),
    'відстань до сусіда': (1 - inter).round(3),
    'виразність': margin.round(3),
    'повнота опорної': [round(ref_metrics['recall'][c], 3) for c in ALL50],
})
print('\nнайвиразніші класи:')
print(distinct.nlargest(8, 'виразність').to_string(index=False))

_rho_size = spearmanr(distinct['у навчальній'], distinct['повнота опорної'])
_rho_dist = spearmanr(distinct['виразність'], distinct['повнота опорної'])
print(f'\nкореляція повноти з розміром класу : {_rho_size.statistic:+.3f} '
      f'(p={_rho_size.pvalue:.4f})')
print(f'кореляція повноти з виразністю     : {_rho_dist.statistic:+.3f} '
      f'(p={_rho_dist.pvalue:.4f})')

_tail_margin = distinct.loc[distinct['смуга'] == 'рідкісні', 'виразність']
_head_margin = distinct.loc[distinct['смуга'] == 'численні', 'виразність']
print(f'\nсередня виразність: рідкісні {_tail_margin.mean():+.3f}, '
      f'численні {_head_margin.mean():+.3f}')
print('гіпотеза «рідкісні художники виразніші» '
      + ('підтверджується на цих даних' if _tail_margin.mean() > _head_margin.mean()
         else 'НЕ підтверджується на цих даних'))
distinct.to_csv(RESULTS / 'raw' / 'nb05_distinctiveness.csv', index=False,
                encoding='utf-8')'''


EMBED_PLOT = r'''fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))
colours = {'численні': 'crimson', 'середні': 'darkorange', 'рідкісні': 'royalblue'}

for band, colour in colours.items():
    part = distinct[distinct['смуга'] == band]
    axes[0].scatter(part['у навчальній'], part['виразність'], s=34, alpha=0.85,
                    color=colour, label=band)
    axes[1].scatter(part['виразність'], part['повнота опорної'], s=34, alpha=0.85,
                    color=colour, label=band)

for _, row in distinct[distinct['смуга'] == 'рідкісні'].iterrows():
    axes[0].annotate(row['художник'].split()[-1], (row['у навчальній'], row['виразність']),
                     fontsize=7, xytext=(3, 3), textcoords='offset points')
    axes[1].annotate(row['художник'].split()[-1], (row['виразність'], row['повнота опорної']),
                     fontsize=7, xytext=(3, 3), textcoords='offset points')

axes[0].set_xscale('log')
axes[0].set_xlabel('зображень у навчальній вибірці (лог. шкала)')
axes[0].set_ylabel('виразність стилю')
axes[0].set_title('Чи виразніші рідкісні художники?', fontsize=11)
axes[1].set_xlabel('виразність стилю')
axes[1].set_ylabel('повнота опорної моделі')
axes[1].set_title('Виразність проти якості розпізнавання', fontsize=11)
for ax in axes:
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
plt.tight_layout()
plt.savefig(RESULTS / 'nb05_distinctiveness.png', dpi=110, bbox_inches='tight')
plt.show()'''


# ----------------------------------------------------------- текстурна гіпотеза
TEXTURE = r'''# Kateryna's concrete intuition, stated in measurable form: a Pollock is mostly
# high-frequency noise, so the tail classes might be separable by texture alone,
# independently of how many examples they have.
#
# Three hand-made statistics per painting, no learning involved:
#   high_freq    - share of spectral energy outside the low-frequency disc
#   edges        - mean absolute gradient (density of brush edges)
#   colour_spread- mean per-channel standard deviation (palette width)
from PIL import Image

TEXTURE_SAMPLE = 40


def texture_stats(path, size=256):
    with Image.open(path) as image:
        gray = np.asarray(image.convert('L').resize((size, size), Image.BILINEAR),
                          dtype=np.float32) / 255.0
        small = np.asarray(image.convert('RGB').resize((64, 64), Image.BILINEAR),
                           dtype=np.float32) / 255.0
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(gray - gray.mean())))
    grid = np.mgrid[:size, :size] - size / 2.0
    radius = np.sqrt(grid[0] ** 2 + grid[1] ** 2)
    gy, gx = np.gradient(gray)
    return {
        'high_freq': float(spectrum[radius > size / 8].sum() / max(spectrum.sum(), 1e-9)),
        'edges': float(np.abs(gy).mean() + np.abs(gx).mean()),
        'colour_spread': float(small.reshape(-1, 3).std(axis=0).mean()),
    }


rows = []
rng = np.random.default_rng(SEED)
for class_dir in ALL50:
    files = sorted((DATA_DIR / 'train' / class_dir).glob('*.jpg'))
    if len(files) > TEXTURE_SAMPLE:
        files = [files[i] for i in rng.choice(len(files), TEXTURE_SAMPLE, replace=False)]
    for path in files:
        try:
            rows.append({'клас': class_dir, 'художник': label(class_dir),
                         'смуга': BAND_TITLE[band_of(class_dir)], **texture_stats(path)})
        except Exception as exc:
            print(f'  пропущено {path.name}: {type(exc).__name__}')

texture = pd.DataFrame(rows)
by_class = texture.groupby(['художник', 'смуга'], as_index=False).mean(numeric_only=True)
print(f'виміряно {len(texture)} зображень у {texture["клас"].nunique()} класах')
print('\nнайбільше високочастотної енергії:')
print(by_class.nlargest(8, 'high_freq').round(4).to_string(index=False))

_zscore = ((by_class['high_freq'] - by_class['high_freq'].mean())
           / max(by_class['high_freq'].std(), 1e-9))
by_class['z високочастотності'] = _zscore.round(2)
for _artist in ('Jackson Pollock', 'Vincent van Gogh', 'Rembrandt'):
    _row = by_class[by_class['художник'] == _artist]
    if not _row.empty:
        print(f'  {_artist:<22} z = {_row["z високочастотності"].iloc[0]:+.2f}')

# How often a painting by the noisiest artist really is in the noisiest decile:
# a bounded, checkable version of "Pollock is recognisable by his texture".
_cut = texture['high_freq'].quantile(0.9)
_loud = texture.groupby('художник')['high_freq'].apply(lambda s: float((s > _cut).mean()))
print('\nчастка картин у верхньому децилі високочастотності:')
print(_loud.nlargest(5).round(3).to_string())
by_class.to_csv(RESULTS / 'raw' / 'nb05_texture.csv', index=False, encoding='utf-8')'''


TEXTURE_PLOT = r'''fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))
colours = {'численні': 'crimson', 'середні': 'darkorange', 'рідкісні': 'royalblue'}

for band, colour in colours.items():
    part = by_class[by_class['смуга'] == band]
    axes[0].scatter(part['edges'], part['high_freq'], s=36, alpha=0.85,
                    color=colour, label=band)
for _, row in by_class.nlargest(6, 'high_freq').iterrows():
    axes[0].annotate(row['художник'].split()[-1], (row['edges'], row['high_freq']),
                     fontsize=7, xytext=(3, 3), textcoords='offset points')
axes[0].set_xlabel('щільність країв')
axes[0].set_ylabel('частка високочастотної енергії')
axes[0].set_title('Текстура за класами (середнє по класу)', fontsize=11)

_order = by_class.nlargest(12, 'high_freq')
axes[1].barh(_order['художник'][::-1], _order['high_freq'][::-1],
             color=[colours[b] for b in _order['смуга'][::-1]])
axes[1].set_xlabel('частка високочастотної енергії')
axes[1].set_title('Дванадцять «найшумніших» художників', fontsize=11)
for ax in axes:
    ax.grid(alpha=0.3)
axes[0].legend(fontsize=8)
plt.tight_layout()
plt.savefig(RESULTS / 'nb05_texture.png', dpi=110, bbox_inches='tight')
plt.show()'''


# ------------------------------------------------------------- інструментарій
TOOLS = r'''# The long-tail toolbox. Every tool is one named switch, so that any two runs
# differ in exactly one of them.
WEIGHT_SCHEME = 'inverse'      # inverse | effective | sqrt | none
SAMPLING = 'instance'          # instance | balanced | balanced_crop | selfmix | crop
TARGET_PER_CLASS = int(np.median(list(TRAIN_COUNTS.values())))
CROP_SHORT = 288
print('цільова кількість на клас при збалансованому семплюванні:', TARGET_PER_CLASS)


def _train_counts(class_names):
    return np.array([max(len(list((DATA_DIR / 'train' / c).glob('*.jpg'))), 1)
                     for c in class_names], dtype=float)


def class_weights_for(class_names):
    """Shadows the plain inverse-frequency version from the shared data cell.

    'effective' is the class-balanced weighting of Cui et al. (2019): the weight
    follows the effective number of samples (1 - b^n) / (1 - b) rather than n,
    which stops a 17-image class from getting a thirty-fold multiplier on every
    gradient while its images stay nearly identical to each other.
    """
    if WEIGHT_SCHEME == 'none':
        return None
    counts = _train_counts(class_names)
    if WEIGHT_SCHEME == 'inverse':
        weights = counts.sum() / (len(counts) * counts)
    elif WEIGHT_SCHEME == 'sqrt':
        weights = np.sqrt(counts.sum() / counts)
    elif WEIGHT_SCHEME == 'effective':
        beta = 0.999
        weights = (1.0 - beta) / (1.0 - beta ** counts)
    else:
        raise ValueError(f'невідома схема ваг: {WEIGHT_SCHEME}')
    weights = weights * len(counts) / weights.sum()
    return {i: float(w) for i, w in enumerate(weights)}


def sparse_focal(gamma=2.0):
    """Focal loss for integer labels (Lin et al., 2017).

    Keras 3 ships only the categorical form, and one-hot encoding fifty classes
    just to use it is pointless. Down-weighting easy examples shifts capacity
    towards the hard ones, which on a long-tailed set are mostly the rare ones.
    """
    def focal(y_true, y_pred):
        index = tf.cast(tf.reshape(y_true, (-1, 1)), tf.int32)
        p = tf.gather(tf.cast(y_pred, tf.float32), index, batch_dims=1)
        p = tf.clip_by_value(tf.squeeze(p, axis=-1), 1e-7, 1.0)
        return -tf.pow(1.0 - p, gamma) * tf.math.log(p)

    focal.__name__ = f'focal_gamma{gamma:g}'
    return focal


def class_files(class_dir):
    return [str(p) for p in sorted((DATA_DIR / 'train' / class_dir).glob('*.jpg'))]


def balanced_train(class_names, img_size, batch, target=None, view='square'):
    """Oversample every class to the same count per epoch.

    class_weight reweights the loss but still shows the network one Pollock per
    forty van Goghs; resampling changes what it actually sees. The two are not
    the same intervention and are measured separately.

    view='crop' takes a different window of the painting each time instead of
    the same squashed copy, which is what makes oversampling seventeen images
    worth anything.
    """
    target = target or TARGET_PER_CLASS
    parts = []
    for index, class_dir in enumerate(class_names):
        files = class_files(class_dir)
        if not files:
            continue
        ds = tf.data.Dataset.from_tensor_slices((files, [index] * len(files)))
        ds = ds.shuffle(len(files), seed=SEED, reshuffle_each_iteration=True)
        parts.append(ds.repeat().take(target))
    merged = parts[0]
    for part in parts[1:]:
        merged = merged.concatenate(part)
    merged = merged.shuffle(8192, seed=SEED)
    if view == 'crop':
        merged = merged.map(lambda p, y: (decode_short_side(p, CROP_SHORT), y),
                            num_parallel_calls=AUTOTUNE)
        merged = merged.map(
            lambda i, y: (tf.image.random_crop(i, (img_size, img_size, 3)), y),
            num_parallel_calls=AUTOTUNE)
    else:
        merged = merged.map(lambda p, y: (decode_square(p, img_size), y),
                            num_parallel_calls=AUTOTUNE)
    return merged.batch(batch).prefetch(AUTOTUNE)


def selfmix_train(class_names, img_size, batch, target=None, alpha=0.4):
    """Blend two paintings of the SAME artist into a new training image.

    Mixup across classes would need soft labels and a different loss; mixing
    within one class keeps the integer label intact and still manufactures
    views the network has not seen. Nothing enters from outside the dataset —
    seventeen Pollocks stay seventeen Pollocks, just recombined.

    The blend keeps one painting dominant (lambda in [1-alpha, 1]), otherwise
    the result stops looking like a painting at all.
    """
    target = target or TARGET_PER_CLASS

    def blend(path_a, path_b, index):
        first, second = decode_square(path_a, img_size), decode_square(path_b, img_size)
        lam = tf.random.uniform([], minval=1.0 - alpha, maxval=1.0)
        return lam * first + (1.0 - lam) * second, index

    parts = []
    for index, class_dir in enumerate(class_names):
        files = class_files(class_dir)
        if not files:
            continue
        first = (tf.data.Dataset.from_tensor_slices(files)
                 .shuffle(len(files), seed=SEED, reshuffle_each_iteration=True).repeat())
        second = (tf.data.Dataset.from_tensor_slices(files)
                  .shuffle(len(files), seed=SEED + 1 + index,
                           reshuffle_each_iteration=True).repeat())
        pairs = tf.data.Dataset.zip((first, second)).take(target)
        parts.append(pairs.map(lambda a, b, i=index: blend(a, b, i),
                               num_parallel_calls=AUTOTUNE))
    merged = parts[0]
    for part in parts[1:]:
        merged = merged.concatenate(part)
    return merged.shuffle(2048, seed=SEED).batch(batch).prefetch(AUTOTUNE)


def crop_train(class_names, img_size, batch):
    """Random windows at native scale instead of squashing the whole canvas.

    A brushstroke is a high-frequency texture: scaling a 320 px painting to
    224x224 and distorting its aspect ratio destroys exactly the detail that
    separates Pollock's drips from Monet's dabs.
    """
    paths, labels = file_label_list(class_names, 'train')
    return (tf.data.Dataset.from_tensor_slices((paths, labels))
            .shuffle(len(paths), seed=SEED, reshuffle_each_iteration=True)
            .map(lambda p, y: (decode_short_side(p, CROP_SHORT), y),
                 num_parallel_calls=AUTOTUNE)
            .map(lambda i, y: (tf.image.random_crop(i, (img_size, img_size, 3)), y),
                 num_parallel_calls=AUTOTUNE)
            .batch(batch).prefetch(AUTOTUNE))


def whole_scores(model, class_names, img_size=224, split='test'):
    """Predictions on whole squashed canvases, in file_label_list order.

    image_dataset_from_directory would do the same job, but its ordering is its
    own business; the two views have to be combined image by image later, so
    both are built from the same file list.
    """
    paths, labels = file_label_list(class_names, split)
    ds = (tf.data.Dataset.from_tensor_slices(paths)
          .map(lambda p: decode_square(p, img_size), num_parallel_calls=AUTOTUNE)
          .batch(32).prefetch(AUTOTUNE))
    return model.predict(ds, verbose=0), np.array(labels)


def five_crop_scores(model, class_names, img_size=224, split='test'):
    """Average the prediction over five windows of each painting."""
    paths, labels = file_label_list(class_names, split)

    def crops(image):
        h, w = tf.shape(image)[0], tf.shape(image)[1]
        offsets = [(0, 0), (0, w - img_size), (h - img_size, 0),
                   (h - img_size, w - img_size),
                   ((h - img_size) // 2, (w - img_size) // 2)]
        return tf.stack([tf.image.crop_to_bounding_box(image, y, x, img_size, img_size)
                         for y, x in offsets])

    ds = (tf.data.Dataset.from_tensor_slices(paths)
          .map(lambda p: crops(decode_short_side(p, CROP_SHORT)),
               num_parallel_calls=AUTOTUNE)
          .batch(8).prefetch(AUTOTUNE))
    chunks = []
    for batch_crops in ds:
        n = int(tf.shape(batch_crops)[0])
        flat = tf.reshape(batch_crops, (-1, img_size, img_size, 3))
        chunks.append(model.predict(flat, verbose=0).reshape(n, 5, -1).mean(axis=1))
    return np.concatenate(chunks), np.array(labels)


_plain_make_datasets = make_datasets


EVEN_EPOCH = ('balanced', 'balanced_crop', 'selfmix')


def make_datasets(class_names, img_size=224, batch=32):
    train, val, test = _plain_make_datasets(class_names, img_size, batch)
    if SAMPLING == 'balanced':
        train = balanced_train(class_names, img_size, batch)
    elif SAMPLING == 'balanced_crop':
        train = balanced_train(class_names, img_size, batch, view='crop')
    elif SAMPLING == 'selfmix':
        train = selfmix_train(class_names, img_size, batch)
    elif SAMPLING == 'crop':
        train = crop_train(class_names, img_size, batch)
    return train, val, test


def compile_model(model, cfg, classes):
    # Steps per epoch feed the cosine schedule, and the resampling modes change
    # how many steps an epoch actually has.
    if SAMPLING in EVEN_EPOCH:
        steps = -(-len(classes) * TARGET_PER_CLASS // cfg.get('batch', 32))
    else:
        steps = -(-count_steps(classes) // cfg.get('batch', 32))
    loss = (sparse_focal(cfg.get('gamma', 2.0)) if cfg.get('loss') == 'focal'
            else 'sparse_categorical_crossentropy')
    model.compile(optimizer=make_optimizer(cfg, steps), loss=loss, metrics=['accuracy'])
    return model


def build_long_tail(cfg, classes):
    if not cfg.get('init_from'):
        return build_transfer(cfg, classes)
    source = MODELS_DIR / f"{cfg['init_from']}.keras"
    if not source.exists():
        raise FileNotFoundError(f'немає {source} — спочатку виконайте {cfg["init_from"]}')
    model = keras.models.load_model(source, compile=False)
    if cfg.get('classifier_only'):
        for layer in model.layers:
            layer.trainable = False
        model.layers[-1].trainable = True
        trainable = sum(int(np.prod(w.shape)) for w in model.trainable_weights)
        print(f'навчається лише класифікатор: {trainable:,} параметрів')
    else:
        unfreeze(find_backbone(model), cfg.get('unfreeze', 0.2))
    return compile_model(model, cfg, classes)


def run_cfg(cfg):
    """The shared run(), with this notebook's switches applied around it."""
    global WEIGHT_SCHEME, SAMPLING
    previous = (WEIGHT_SCHEME, SAMPLING)
    WEIGHT_SCHEME = cfg.get('weights', 'inverse')
    SAMPLING = cfg.get('sampling', 'instance')
    try:
        record = run({**cfg, 'classes': ALL50}, build_long_tail)
    finally:
        WEIGHT_SCHEME, SAMPLING = previous
    evaluate_saved(cfg['name'], cfg['title'])
    return record


LT_DEFAULTS = {'backbone': 'EfficientNetB0', 'augment': 'light', 'img_size': 224,
               'batch': 32, 'dropout': 0.3}
print('інструментарій готовий')'''


# ---------------------------------------------------------------- базові прогони
RUNS_BASE = r'''# C0-C2: the floor and the standard answer.
#
# C0 is the shared parent of every fine-tuning run below, trained with no
# rebalancing at all, so that the comparisons downstream are not contaminated
# by the parent's own weighting. C1 is honest fine-tuning without any long-tail
# tool; C2 adds the one thing the course lab reflex reaches for first.
run_cfg({**LT_DEFAULTS, 'name': 'c0_frozen',
         'title': 'заморожена база, без зважування',
         'lr': 1e-3, 'epochs': 20, 'weights': 'none'})

FT = {**LT_DEFAULTS, 'init_from': 'c0_frozen', 'unfreeze': 1.0, 'lr': 1e-4,
      'schedule': 'cosine', 'epochs': 15, 'patience': 4}

run_cfg({**FT, 'name': 'c1_plain',
         'title': 'донавчання всієї бази, без жодних засобів',
         'weights': 'none'})

run_cfg({**FT, 'name': 'c2_inverse',
         'title': 'зважування класів, обернене до частоти',
         'class_weight': True, 'weights': 'inverse'})'''


RUNS_LOSS = r'''# C3-C5: three different places to intervene, one at a time.
#   C3 - the weights themselves (effective number instead of inverse frequency)
#   C4 - the loss (focal instead of cross-entropy)
#   C5 - what the network is shown (balanced resampling instead of reweighting)
run_cfg({**FT, 'name': 'c3_effective',
         'title': 'зважування за ефективною кількістю, beta=0.999',
         'class_weight': True, 'weights': 'effective'})

run_cfg({**FT, 'name': 'c4_focal',
         'title': 'фокальна функція втрат, gamma=2',
         'loss': 'focal', 'gamma': 2.0, 'weights': 'none'})

run_cfg({**FT, 'name': 'c5_balanced',
         'title': 'збалансоване семплювання замість зважування',
         'sampling': 'balanced', 'weights': 'none'})'''


CRT = r'''# C6: retrain the classifier only (Kang et al., 2020).
#
# The idea that makes this worth a separate run: a long-tailed set still teaches
# good features, and what it mainly spoils is the decision boundary, because the
# last layer sees forty times more van Goghs. So the representation is kept
# exactly as C1 learned it, everything is frozen, and only the final 50-way
# layer is retrained on balanced batches. It costs a fraction of a full run.
run_cfg({**LT_DEFAULTS, 'name': 'c6_classifier_only',
         'title': 'перенавчання лише класифікатора на збалансованих партіях',
         'init_from': 'c1_plain', 'classifier_only': True,
         'sampling': 'balanced', 'weights': 'none',
         'lr': 1e-3, 'epochs': 10, 'patience': 3})'''


POSTHOC = r'''# C7: no training at all — correct the scores afterwards.
#
# A softmax trained on an imbalanced set learns the prior as well as the
# evidence. Subtracting tau * log(prior) from the log-scores removes that bias
# (Menon et al., 2021, "logit adjustment"). tau is chosen on the VALIDATION
# subset; the test subset only reports the result.
priors = _train_counts(ALL50)
priors = priors / priors.sum()

_model = keras.models.load_model(MODELS_DIR / 'c1_plain.keras', compile=False)
val_probs = _model.predict(VAL_DS, verbose=0)
test_probs = _model.predict(TEST_DS, verbose=0)
del _model
keras.backend.clear_session()


def adjust(probs, tau):
    return np.log(probs + 1e-9) - tau * np.log(priors)[None, :]


def balanced_on(scores, y_true):
    y_pred = scores.argmax(axis=1)
    per_class = [float((y_pred[y_true == i] == i).mean())
                 for i in range(len(ALL50)) if (y_true == i).any()]
    return float(np.mean(per_class))


TAUS = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5)
tau_rows = [{'tau': t, 'збалансована на перевірочній': round(balanced_on(adjust(val_probs, t), Y_VAL), 4)}
            for t in TAUS]
tau_frame = pd.DataFrame(tau_rows)
print(tau_frame.to_string(index=False))

BEST_TAU = float(tau_frame.loc[tau_frame['збалансована на перевірочній'].idxmax(), 'tau'])
print(f'\nобрано tau = {BEST_TAU} (за перевірочною вибіркою)')
evaluate_saved('c7_logit_adjust',
               f'поправка на апріорні ймовірності, tau={BEST_TAU:g}',
               scores=adjust(test_probs, BEST_TAU), kind='без навчання')'''


PROTO = r'''# C8: classify by nearest class centroid in the ImageNet feature space, with no
# training whatsoever. This is the few-shot question in its purest form: if a
# rare artist really is distinctive, a handful of examples should be enough to
# place a centroid, and the k-shot curve should flatten early.
TEST_PATHS, TEST_LABELS = file_label_list(ALL50, 'test')
TEST_LABELS = np.array(TEST_LABELS)
E_TEST = embed(TEST_PATHS)


def prototype_scores(shots=None, seed=SEED):
    rng = np.random.default_rng(seed)
    centroids = []
    for i in range(len(ALL50)):
        index = np.flatnonzero(TRAIN_LABELS == i)
        if shots is not None and len(index) > shots:
            index = rng.choice(index, shots, replace=False)
        centroids.append(E_TRAIN[index].mean(axis=0))
    matrix = np.stack(centroids)
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9)
    return E_TEST @ matrix.T


shots_rows = []
for shots in (1, 5, 10, 20, 50, None):
    scores = prototype_scores(shots)
    metrics = record_tail(f'proto_{shots or "all"}', f'прототипи, {shots or "усі"} зразків',
                          scores, TEST_LABELS, kind='без навчання', store=False)
    shots_rows.append({'зразків на клас': shots or len(E_TRAIN) // len(ALL50),
                       'усі класи': round(metrics['balanced_accuracy'], 4),
                       'рідкісні': round(metrics['band_recall']['tail'], 4),
                       'численні': round(metrics['band_recall']['head'], 4)})

shots_frame = pd.DataFrame(shots_rows)
print('\n' + shots_frame.to_string(index=False))
record_tail('c8_prototypes', 'прототипи в ознаках ImageNet, без навчання',
            prototype_scores(None), TEST_LABELS, kind='без навчання')'''


PROTO_PLOT = r'''fig, ax = plt.subplots(figsize=(6.6, 4.3))
ax.plot(shots_frame['зразків на клас'], shots_frame['рідкісні'], color='royalblue',
        marker='o', label='рідкісні класи')
ax.plot(shots_frame['зразків на клас'], shots_frame['численні'], color='crimson',
        ls='--', marker='s', label='численні класи')
ax.axhline(ref_metrics['band_recall']['tail'], color='seagreen', ls=':',
           label='опорна модель, рідкісні')
ax.set_xscale('log')
ax.set_xlabel('зразків на клас для побудови прототипу (лог. шкала)')
ax.set_ylabel('середня повнота')
ax.set_title('Скільки картин потрібно, щоб упізнати художника', fontsize=11)
ax.grid(alpha=0.3)
ax.legend(fontsize=8)
plt.tight_layout()
plt.savefig(RESULTS / 'nb05_fewshot.png', dpi=110, bbox_inches='tight')
plt.show()'''










RUNS_VIEWS = r'''# C9-C10: get more out of the same paintings, with nothing added from outside.
#
# C9 recombines an artist's own work: two of his paintings blended into one
# training image. Seventeen Pollocks stay seventeen Pollocks — but the network
# sees combinations of them it has not seen before. Compared against C5, which
# oversamples the same images unchanged, it isolates the blending itself.
#
# C10 oversamples like C5 but takes a different window of the canvas each time.
# This is the cheap version of the idea the paintings suggest: for an artist
# whose signature repeats across the canvas, one painting is worth many samples.
run_cfg({**FT, 'name': 'c9_selfmix',
         'title': 'перемішування робіт художника між собою',
         'sampling': 'selfmix', 'weights': 'none'})

run_cfg({**FT, 'name': 'c10_balanced_crop',
         'title': 'збалансоване семплювання вирізками',
         'sampling': 'balanced_crop', 'weights': 'none'})'''


PATCH = r'''# C11: the texture hypothesis as a training protocol.
#
# Everywhere above, a painting is squashed into 224x224, which throws away the
# brushstroke scale. Here the short side goes to 288 px with the aspect ratio
# intact and the network sees a random 224 window of the canvas; at test time
# the prediction is averaged over five windows. If Pollock is recognisable by
# texture rather than by composition, this is where it should show.
run_cfg({**FT, 'name': 'c11_crops',
         'title': 'навчання на вирізках у власному масштабі',
         'sampling': 'crop', 'weights': 'none'})

if 'c11_crops_5crop' not in tail_metrics or FORCE_RERUN:
    _model = keras.models.load_model(MODELS_DIR / 'c11_crops.keras', compile=False)
    _scores, _labels = five_crop_scores(_model, ALL50)
    del _model
    keras.backend.clear_session()
    record_tail('c11_crops_5crop', 'вирізки + усереднення по п\'яти вікнах',
                _scores, _labels, kind='навчання')
else:
    print('[c11_crops_5crop] уже виміряно — пропускаю')'''


VIEWS = r'''# C12-C13: the actual lesson from looking at the paintings.
#
# A window of a Pollock carries his whole signature — the drips repeat across
# the canvas, so one painting is worth many near-independent samples, and the
# 2.7x5.3 m canvas squashed into 320 px loses the brushwork entirely. A window
# of a Mondrian, on the other hand, is often a plain red rectangle, and a window
# of a Caravaggio is often black background: there the signature IS the whole
# canvas, and cropping destroys it.
#
# So the two views are not rivals — they suit different artists. Which suits
# which is decided on the VALIDATION subset; the test subset only reports.
WHOLE_RUN, CROP_RUN = 'c1_plain', 'c11_crops'


def view_scores(run_name, split, cropped):
    model = keras.models.load_model(MODELS_DIR / f'{run_name}.keras', compile=False)
    scores, labels = (five_crop_scores(model, ALL50, split=split) if cropped
                      else whole_scores(model, ALL50, split=split))
    del model
    keras.backend.clear_session()
    return scores, labels


def per_class_recall(scores, y_true):
    predicted = scores.argmax(axis=1)
    return np.array([float((predicted[y_true == i] == i).mean())
                     if (y_true == i).any() else np.nan
                     for i in range(len(ALL50))])


val_whole, y_val_ordered = view_scores(WHOLE_RUN, 'val', cropped=False)
val_crop, _ = view_scores(CROP_RUN, 'val', cropped=True)
test_whole, y_test_ordered = view_scores(WHOLE_RUN, 'test', cropped=False)
test_crop, _ = view_scores(CROP_RUN, 'test', cropped=True)

recall_whole = per_class_recall(val_whole, y_val_ordered)
recall_crop = per_class_recall(val_crop, y_val_ordered)
USE_CROP = np.nan_to_num(recall_crop) > np.nan_to_num(recall_whole)
print(f'вирізки виграли на перевірочній у {int(USE_CROP.sum())} класах із '
      f'{len(ALL50)}; серед рідкісних — '
      f'{int(sum(USE_CROP[ALL50.index(c)] for c in TAIL))} із {len(TAIL)}')

# Plain average first: it needs no per-class decision at all, so it is the
# honest baseline for the per-class choice below.
record_tail('c12_ensemble', 'середнє двох масштабів',
            0.5 * (test_whole + test_crop), y_test_ordered)

# Per-class choice. Caveat worth stating in the report: the columns come from
# two different models, and softmax outputs of different models are not strictly
# on one scale. Both are the same architecture trained on the same data, which
# makes it defensible, and C12 above is the calibration-free alternative.
record_tail('c13_per_class_view',
            'масштаб обрано для кожного класу за перевірочною вибіркою',
            np.where(USE_CROP[None, :], test_crop, test_whole), y_test_ordered)

view_frame = pd.DataFrame({
    'художник': [label(c) for c in ALL50],
    'смуга': [BAND_TITLE[band_of(c)] for c in ALL50],
    'у навчальній': [TRAIN_COUNTS[c] for c in ALL50],
    'перевірочна: ціле': recall_whole.round(3),
    'перевірочна: вирізки': recall_crop.round(3),
    'обрано': np.where(USE_CROP, 'вирізки', 'ціле полотно'),
})
print('\nрідкісні класи:')
print(view_frame[view_frame['смуга'] == 'рідкісні']
      .sort_values('у навчальній').to_string(index=False))

# Does the texture statistic predict the choice? If it does, the rule is not a
# coincidence of this validation split but a property of the painting.
_hf = by_class.set_index('художник')['high_freq']
view_frame['високочастотність'] = [
    float(_hf.get(name, np.nan)) for name in view_frame['художник']]
_crop_hf = view_frame.loc[view_frame['обрано'] == 'вирізки', 'високочастотність'].dropna()
_whole_hf = view_frame.loc[view_frame['обрано'] == 'ціле полотно',
                           'високочастотність'].dropna()
print(f'\nсередня високочастотність: де виграли вирізки {_crop_hf.mean():.4f}, '
      f'де виграло ціле полотно {_whole_hf.mean():.4f}')

# A difference in the fourth decimal is not a finding. The verdict is only
# pronounced if the two groups actually separate, so the report cannot claim a
# rule that rests on rounding.
if len(_crop_hf) >= 3 and len(_whole_hf) >= 3:
    from scipy.stats import mannwhitneyu

    _test = mannwhitneyu(_crop_hf, _whole_hf, alternative='greater')
    print(f'перевірка Манна-Вітні: p = {_test.pvalue:.4f}')
    print('текстурна статистика '
          + ('передбачає вибір масштабу' if _test.pvalue < 0.05
             else 'НЕ передбачає вибору масштабу на цих даних'))
else:
    print('груп замало для перевірки значущості — висновку про текстуру не роблю')
view_frame.to_csv(RESULTS / 'raw' / 'nb05_view_choice.csv', index=False,
                  encoding='utf-8')'''


# ------------------------------------------------------------------- підсумок
TABLE = r'''# Everything measured in this notebook, ranked by what it was all for: mean
# per-class recall on the rare artists.
summary = pd.DataFrame([{
    'метод': m['name'],
    'що зроблено': m['title'],
    'спосіб': m['kind'],
    'accuracy': round(m['accuracy'], 4),
    'збалансована': round(m['balanced_accuracy'], 4),
    'macro F1': round(m['macro_f1'], 4),
    'численні': round(m['band_recall']['head'], 3),
    'середні': round(m['band_recall']['mid'], 3),
    'рідкісні': round(m['band_recall']['tail'], 3),
} for m in tail_metrics.values()]).sort_values('рідкісні', ascending=False)
print(summary.to_string(index=False))
summary.to_csv(RESULTS / 'raw' / 'nb05_table.csv', index=False, encoding='utf-8')

BEST_TAIL = summary.iloc[0]['метод']
REF_TAIL = ref_metrics['band_recall']['tail']
BEST_TAIL_VALUE = float(summary.iloc[0]['рідкісні'])
print(f'\nнайкраще на рідкісних класах: {BEST_TAIL} — {BEST_TAIL_VALUE:.3f} '
      f'проти {REF_TAIL:.3f} в опорної моделі ({BEST_TAIL_VALUE - REF_TAIL:+.3f})')

# Standard error of a per-class recall on a class with n test images is
# sqrt(p(1-p)/n); on a seven-image class that is about 0.17, so differences of
# a few hundredths on the tail band mean nothing. Printed, not hidden.
_tail_test = [int((Y_TEST == ALL50.index(c)).sum()) for c in TAIL]
if _tail_test:
    print(f'тестових зображень у рідкісних класах: {sum(_tail_test)} '
          f'(від {min(_tail_test)} до {max(_tail_test)} на клас)')
    print('типова стандартна похибка повноти одного рідкісного класу: '
          f'{np.sqrt(0.25 / np.mean(_tail_test)):.3f}')'''


TABLE_PLOT = r'''order = summary.sort_values('рідкісні')
fig, ax = plt.subplots(figsize=(10.5, max(4.2, 0.42 * len(order))))
y = np.arange(len(order))
height = 0.26
ax.barh(y + height, order['численні'], height, color='crimson', label='численні')
ax.barh(y, order['середні'], height, color='darkorange', label='середні')
ax.barh(y - height, order['рідкісні'], height, color='royalblue', label='рідкісні')
ax.axvline(REF_TAIL, color='seagreen', ls=':', lw=1.4,
           label='опорна модель, рідкісні')
ax.set_yticks(y)
ax.set_yticklabels(order['метод'], fontsize=8)
ax.set_xlabel('середня повнота за класами смуги')
ax.set_title('Що саме допомагає рідкісним художникам', fontsize=12)
ax.grid(alpha=0.3, axis='x')
ax.legend(fontsize=8, loc='lower right')
plt.tight_layout()
plt.savefig(RESULTS / 'nb05_bands.png', dpi=110, bbox_inches='tight')
plt.show()


fig, ax = plt.subplots(figsize=(8.2, 5.0))
sizes = np.array([TRAIN_COUNTS[c] for c in ALL50])
ax.scatter(sizes, [ref_metrics['recall'][c] for c in ALL50], s=34, alpha=0.8,
           color='seagreen', label=f'опорна ({REF})')
best = tail_metrics[BEST_TAIL]
ax.scatter(sizes, [best['recall'][c] for c in ALL50], s=34, alpha=0.8,
           color='royalblue', marker='^', label=f'найкраща ({BEST_TAIL})')
for class_dir in TAIL:
    ax.annotate(label(class_dir).split()[-1],
                (TRAIN_COUNTS[class_dir], best['recall'][class_dir]),
                fontsize=7, xytext=(3, 3), textcoords='offset points')
ax.axvline(TAIL_MAX, color='grey', ls='--', lw=1,
           label=f'межа рідкісних ({TAIL_MAX})')
ax.set_xscale('log')
ax.set_xlabel('зображень у навчальній вибірці (лог. шкала)')
ax.set_ylabel('повнота класу')
ax.set_title('Повнота проти розміру класу: до і після', fontsize=12)
ax.grid(alpha=0.3)
ax.legend(fontsize=8)
plt.tight_layout()
plt.savefig(RESULTS / 'nb05_recall_vs_size.png', dpi=110, bbox_inches='tight')
plt.show()'''


CONCLUSIONS = r'''# Conclusions computed from the numbers above rather than typed in by hand, so
# that the text in the report cannot drift away from what was measured.
print('ВИСНОВКИ\n')

by_tail = {name: m['band_recall']['tail'] for name, m in tail_metrics.items()}
free = {n: v for n, v in by_tail.items() if tail_metrics[n]['kind'] == 'без навчання'}

print(f'1. Опорна модель {REF}: повнота рідкісних {REF_TAIL:.3f} проти '
      f"{ref_metrics['band_recall']['head']:.3f} на численних. Дисбаланс б'є "
      'саме по тих класах, яких мало.')

print(f'\n2. Найкращий результат на рідкісних класах — {BEST_TAIL} '
      f'({BEST_TAIL_VALUE:.3f}, {BEST_TAIL_VALUE - REF_TAIL:+.3f} до опорної). '
      f"Загальна точність при цьому {tail_metrics[BEST_TAIL]['accuracy']:.4f} "
      f"проти {ref_metrics['accuracy']:.4f}.")

if free:
    best_free = max(free, key=free.get)
    print(f'\n3. Без жодного навчання: {best_free} дає {free[best_free]:.3f} на '
          f'рідкісних класах. Це {free[best_free] - REF_TAIL:+.3f} до опорної '
          'моделі, яку вчили годинами.')

print('\n4. Масштаб погляду. Вирізки виграли на перевірочній вибірці у '
      f'{int(USE_CROP.sum())} класах із {len(ALL50)}, тобто це засіб не для всіх, '
      'а для тих художників, чий підпис повторюється по всьому полотну.')
for name in ('c11_crops', 'c11_crops_5crop', 'c12_ensemble', 'c13_per_class_view'):
    if name in tail_metrics:
        print(f"   {name:<22} рідкісні {tail_metrics[name]['band_recall']['tail']:.3f}")

if 'Jackson_Pollock' in ALL50:
    print('\n5. Поллок — найменший клас '
          f"({TRAIN_COUNTS.get('Jackson_Pollock', 0)} навчальних зображень) і "
          'найчистіший випадок текстурного підпису: крапельний візерунок '
          'однаковий по всьому полотну.')
    for name in (REF, 'c1_plain', BEST_TAIL):
        if name in tail_metrics:
            value = tail_metrics[name]['recall'].get('Jackson_Pollock')
            if value is not None:
                print(f'   {name:<22} повнота Поллока {value:.3f}')

_tail_margin_mean = float(distinct.loc[distinct['смуга'] == 'рідкісні', 'виразність'].mean())
_head_margin_mean = float(distinct.loc[distinct['смуга'] == 'численні', 'виразність'].mean())
print(f'\n6. Гіпотеза про виразність: середня виразність рідкісних класів '
      f'{_tail_margin_mean:+.3f} проти {_head_margin_mean:+.3f} на численних; '
      f'кореляція повноти з виразністю {_rho_dist.statistic:+.3f}, '
      f'з розміром класу {_rho_size.statistic:+.3f}.')

if 'c11_crops_5crop' in tail_metrics and 'c1_plain' in tail_metrics:
    crop_gain = (tail_metrics['c11_crops_5crop']['band_recall']['tail']
                 - tail_metrics['c1_plain']['band_recall']['tail'])
    print(f'\n7. Текстурний протокол (вирізки + п\'ять вікон): {crop_gain:+.3f} '
          'на рідкісних класах до того самого донавчання на стиснутих зображеннях.')'''


EXPORT = r'''# Export: numbers for the report plus a zip to drop into results/incoming/.
NB = 'nb05'
payload = {
    'notebook': NB,
    'tensorflow': tf.__version__,
    'gpu': [d.name for d in tf.config.list_physical_devices('GPU')],
    'reference_run': REF,
    'bands': {'head_min': HEAD_MIN, 'tail_max': TAIL_MAX,
              'members': {b: BANDS_OF[b] for b in BAND_NAMES}},
    'train_counts': TRAIN_COUNTS,
    'external_data_used': False,
    'best_tau': BEST_TAU,
    'view_choice': view_frame.to_dict(orient='records'),
    'few_shot': shots_frame.to_dict(orient='records'),
    'distinctiveness': distinct.to_dict(orient='records'),
    'texture': by_class.to_dict(orient='records'),
    'methods': tail_metrics,
    'best_on_tail': BEST_TAIL,
}
out = RESULTS / 'raw' / f'{NB}.json'
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
print('записано', out)

zip_path = PROJECT_ROOT / f'project_{NB}_results.zip'
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted(RESULTS.rglob('*')):
        if f.is_file() and f.suffix in ('.json', '.png', '.csv', '.md'):
            z.write(f, f.relative_to(RESULTS))
print('зіп:', zip_path, f'({zip_path.stat().st_size / 1e6:.1f} МБ)')

if IN_COLAB:
    from google.colab import files

    files.download(str(zip_path))'''
