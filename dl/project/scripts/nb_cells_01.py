r"""Клітинки ноутбука 01 — набір даних, EDA, очищення, поділ, підготовка.

Робить усе, що умова вимагає від розділу «набір даних»: джерело, опис,
структура, приклади класів, дисбаланс, очищення, стратифікований поділ і
попередня обробка. Решта ноутбуків беруть готове дерево з Drive.

Ключове рішення: класом вважається **художник**, а не тека. В архіві Kaggle
той самий художник трапляється у двох теках із різним записом імені, і без
об'єднання модель училася б відрізняти Дюрера від Дюрера.
"""

UNPACK = r'''# The Kaggle archive sits on Drive; unpack it to local disk, not to Drive —
# unpacking 8k small files into Drive is an order of magnitude slower.
ARCHIVE_NAME = 'archive (3).zip'
RAW_DIR = Path('/content/raw') if IN_COLAB else PROJECT_ROOT / 'data' / 'raw'
RAW_DIR.mkdir(parents=True, exist_ok=True)

mount_drive()
if not any(RAW_DIR.rglob('artists.csv')):
    src = DRIVE_DIR / ARCHIVE_NAME
    if not src.exists():
        raise FileNotFoundError(
            f'немає {src}\n'
            f'залийте архів Kaggle у теку {DRIVE_DIR} під іменем {ARCHIVE_NAME}')
    t0 = time.time()
    with zipfile.ZipFile(src) as z:
        z.extractall(RAW_DIR)
    print(f'розпаковано за {time.time() - t0:.0f} с')
else:
    print('архів уже розпаковано')

CSV_PATH = next(RAW_DIR.rglob('artists.csv'))

# The archive nests folders (images/images/<Artist>/...), and the exact nesting
# has changed between dataset versions. Find the folder with the most class
# subfolders instead of hard-coding a path.
candidates = {}
for p in RAW_DIR.rglob('*'):
    if p.is_dir():
        n = sum(1 for c in p.iterdir() if c.is_dir())
        if n:
            candidates[p] = n
IMAGES_ROOT = max(candidates, key=candidates.get)

print('artists.csv :', CSV_PATH.relative_to(RAW_DIR))
print('тека класів :', IMAGES_ROOT.relative_to(RAW_DIR), f'({candidates[IMAGES_ROOT]} підтек)')'''


ARTISTS_CSV = r'''# artists.csv: the Wikipedia metadata shipped with the dataset.
artists = pd.read_csv(CSV_PATH)
print('розмір таблиці:', artists.shape)
print('колонки      :', list(artists.columns))
print()
print(artists[['name', 'years', 'genre', 'nationality', 'paintings']].head(10).to_string(index=False))

print('\nнаціональності (топ-10):')
print(artists['nationality'].value_counts().head(10).to_string())
print('\nжанри (топ-10):')
print(artists['genre'].value_counts().head(10).to_string())
print('\nкартин за CSV: разом', int(artists['paintings'].sum()),
      '| медіана', int(artists['paintings'].median()),
      '| від', int(artists['paintings'].min()), 'до', int(artists['paintings'].max()))'''


MATCH_NAMES = r'''# Two separate problems live in the folder names, and both are silent.
#
# 1. Folder names use underscores and carry diacritics in forms that do not
#    survive a plain comparison with artists.csv. Normalising to NFC is not
#    enough: composition only works for marks with a precomposed code point,
#    and this archive contains at least one that has none.
# 2. The SAME artist appears in MORE THAN ONE folder, spelled differently —
#    there are two Albrecht Durer folders. Treated as two classes, the model
#    would be asked to tell Durer from Durer, which poisons every metric and
#    makes the confusion matrix meaningless.
#
# 3. Some folder names are MOJIBAKE: the UTF-8 bytes of the umlaut were once
#    read as a single-byte codepage and written back, so the name on disk really
#    contains the characters that garbling produced. One Durer folder went
#    through this once, the other twice. No Unicode normalisation can undo it —
#    the original bytes are gone.
#
# The first two are solved by a key that drops diacritics and anything that is
# not a plain latin letter or digit. The third needs a fallback: whatever is
# still unmatched is compared to the CSV names by string similarity, which
# survives arbitrary garbling of a few characters. Every such match is printed
# with its score so it can be checked by eye.
import difflib
import re
import unicodedata


def strip_marks(text):
    return ''.join(ch for ch in unicodedata.normalize('NFD', str(text))
                   if not unicodedata.combining(ch))


def norm_name(text):
    """Matching key: no diacritics, no punctuation, no non-ASCII, lowercase."""
    text = strip_marks(text).replace('_', ' ').replace('-', ' ')
    text = re.sub(r'[^A-Za-z0-9 ]+', '', text)
    return ' '.join(text.split()).casefold()


folders = sorted((p for p in IMAGES_ROOT.iterdir() if p.is_dir()),
                 key=lambda p: norm_name(p.name))
csv_by_norm = {norm_name(row['name']): row for _, row in artists.iterrows()}

matched, unmatched_folders = {}, []
for folder in folders:
    row = csv_by_norm.get(norm_name(folder.name))
    if row is None:
        unmatched_folders.append(folder.name)
    else:
        matched[folder.name] = row

# Fallback for the garbled names. A wrong guess here would silently merge two
# different artists, so the bar is high (0.80) and everything it does is shown.
FUZZY_THRESHOLD = 0.80
csv_keys = list(csv_by_norm)
fuzzy_matched, still_unmatched = [], []
for folder_name in unmatched_folders:
    key = norm_name(folder_name)
    scored = [(difflib.SequenceMatcher(None, key, k).ratio(), k) for k in csv_keys]
    ratio, best = max(scored)
    if ratio >= FUZZY_THRESHOLD:
        matched[folder_name] = csv_by_norm[best]
        fuzzy_matched.append((folder_name, str(csv_by_norm[best]['name']), ratio))
    else:
        still_unmatched.append(folder_name)
unmatched_folders = still_unmatched

unmatched_csv = [n for n in csv_by_norm if n not in
                 {norm_name(f.name) for f in folders} | {norm_name(matched[f]['name'])
                                                         for f in matched}]

print(f'тек із зображеннями : {len(folders)}')
print(f'рядків у artists.csv: {len(artists)}')
print(f'зіставлено          : {len(matched)}')
print(f'теки без рядка в CSV: {unmatched_folders or "немає"}')
print(f'рядки CSV без теки  : {unmatched_csv or "немає"}')

if fuzzy_matched:
    print('\nзіставлено за схожістю рядків (зіпсовані назви тек):')
    for folder_name, csv_name, ratio in fuzzy_matched:
        print(f'  {folder_name!r}')
        print(f'    -> CSV {csv_name!r}  (подібність {ratio:.2f})')
# repr показує самі код-пойнти: якщо якась тека все одно не зіставилась,
# з виводу видно, що саме в її імені, а не лише як воно друкується.
for name in unmatched_folders:
    print('  не зіставлено:', repr(name))

# Канонічне ім'я класу — з CSV, якщо рядок знайшовся; інакше з назви теки.
CLASS_OF = {}
for folder in folders:
    row = matched.get(folder.name)
    base = str(row['name']) if row is not None else folder.name.replace('_', ' ')
    CLASS_OF[folder.name] = unicodedata.normalize('NFC', ' '.join(base.split()))

FOLDERS_OF_CLASS = {}
for folder_name, class_name in CLASS_OF.items():
    FOLDERS_OF_CLASS.setdefault(class_name, []).append(folder_name)

split_classes = {c: f for c, f in FOLDERS_OF_CLASS.items() if len(f) > 1}
if split_classes:
    print(f'\n!! той самий художник у кількох теках — об\'єдную в один клас:')
    for class_name, names in split_classes.items():
        print(f'   {class_name}:')
        for name in names:
            print(f'      {name!r}')

fuzzy_names = {name for name, _, _ in fuzzy_matched}
differing = [(f.name, matched[f.name]['name']) for f in folders
             if f.name in matched and f.name not in fuzzy_names
             and f.name.replace('_', ' ') != matched[f.name]['name']]
if differing:
    print('\nімена, що збіглися лише після нормалізації:')
    for folder_name, csv_name in differing:
        print(f'  тека {folder_name!r}  <->  CSV {csv_name!r}')

print(f'\nтек: {len(folders)}  ->  класів після об\'єднання: {len(FOLDERS_OF_CLASS)}')'''


COUNTS = r'''# How many paintings each artist actually has on disk, and how badly the
# classes are imbalanced. Counting is per ARTIST, so the folders merged above
# are added together. Nothing here is hard-coded: every number is counted.
all_files = []
for folder in folders:
    all_files.extend(sorted(p for p in folder.iterdir()
                            if p.suffix.lower() in ('.jpg', '.jpeg', '.png')))

files_by_class = {}
for p in all_files:
    files_by_class.setdefault(CLASS_OF[p.parent.name], []).append(p)

no_images = sorted(set(FOLDERS_OF_CLASS) - set(files_by_class))
if no_images:
    print(f'класів без жодного зображення: {len(no_images)} — викидаю')
    for class_name in no_images:
        print('  ', class_name, [repr(n) for n in FOLDERS_OF_CLASS[class_name]])

rows = []
for class_name, files in files_by_class.items():
    row = next((matched[n] for n in FOLDERS_OF_CLASS[class_name] if n in matched), None)
    rows.append({
        'class': class_name,
        'artist': class_name,
        'n_folders': len(FOLDERS_OF_CLASS[class_name]),
        'n_files': len(files),
        'csv_paintings': int(row['paintings']) if row is not None else -1,
        'genre': row['genre'] if row is not None else '?',
        'nationality': row['nationality'] if row is not None else '?',
    })

counts = pd.DataFrame(rows).sort_values('n_files', ascending=False).reset_index(drop=True)
TOTAL_IMAGES = int(counts['n_files'].sum())

print(f'\nусього зображень: {TOTAL_IMAGES} у {len(counts)} класах')
print(f"дисбаланс: від {counts['n_files'].min()} до {counts['n_files'].max()} "
      f"зображень на клас, відношення "
      f"{counts['n_files'].max() / counts['n_files'].min():.1f}:1")
print(f"медіана {int(counts['n_files'].median())}, "
      f"середнє {counts['n_files'].mean():.1f}")

mismatch = counts[(counts['csv_paintings'] >= 0)
                  & (counts['csv_paintings'] != counts['n_files'])]
print(f'\nрозбіжність CSV vs диск: {len(mismatch)} класів')
if len(mismatch):
    print(mismatch[['artist', 'csv_paintings', 'n_files']].head(10).to_string(index=False))

print('\nтоп-10 за кількістю:')
print(counts.head(10)[['artist', 'n_files', 'genre']].to_string(index=False))
print('\nнайрідкісніші 10:')
print(counts.tail(10)[['artist', 'n_files', 'genre']].to_string(index=False))'''


COUNTS_PLOT = r'''# The imbalance, drawn. This chart is the reason the main track uses the
# top-15 artists and the 50-class run needs class weights.
fig, ax = plt.subplots(figsize=(9, 11))
order = counts.sort_values('n_files')
colors = ['crimson' if n < 200 else 'royalblue' for n in order['n_files']]
ax.barh(order['artist'], order['n_files'], color=colors)
ax.set_xlabel('кількість зображень')
ax.set_title(f'Розподіл зображень за художниками ({TOTAL_IMAGES} зображень, '
             f'{len(counts)} класів)', fontsize=12)
ax.grid(axis='x', alpha=0.3)
ax.tick_params(axis='y', labelsize=7)
plt.tight_layout()
plt.savefig(RESULTS / 'nb01_class_balance.png', dpi=110, bbox_inches='tight')
plt.show()'''


IMAGE_PROPS = r'''# What the images physically look like: size, aspect ratio, colour mode.
# A sample is enough here — the full integrity pass over every file comes next.
from PIL import Image

rng = np.random.default_rng(SEED)
sample = rng.choice(np.array(all_files, dtype=object),
                    size=min(400, len(all_files)), replace=False)

# Unreadable files are skipped here rather than handled: the next cell walks
# every file and reports them properly. Letting one broken JPEG abort a survey
# of 400 random images would be the wrong trade.
props, unreadable = [], 0
for path in sample:
    try:
        with Image.open(path) as im:
            props.append({'w': im.width, 'h': im.height, 'mode': im.mode})
    except Exception:
        unreadable += 1
if unreadable:
    print(f'у вибірці не відкрилось {unreadable} файлів — перелік буде нижче')
props = pd.DataFrame(props)
props['short_side'] = props[['w', 'h']].min(axis=1)
props['aspect'] = props['w'] / props['h']

print(f'вибірка {len(props)} зображень')
print(props[['w', 'h', 'short_side', 'aspect']].describe().round(2).to_string())
print('\nкольорові режими:', props['mode'].value_counts().to_dict())

fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
axes[0].hist(props['short_side'], bins=40, color='royalblue')
axes[0].axvline(320, color='crimson', ls='--', label='цільові 320 px')
axes[0].set_title('коротка сторона, px')
axes[0].set_xlabel('px')
axes[0].legend(fontsize=8)
axes[1].hist(props['aspect'], bins=40, color='royalblue')
axes[1].axvline(1.0, color='crimson', ls='--', label='квадрат')
axes[1].set_title('співвідношення сторін (ширина / висота)')
axes[1].legend(fontsize=8)
for ax in axes:
    ax.grid(alpha=0.3)
fig.suptitle('Фізичні властивості зображень', fontsize=12)
plt.tight_layout()
plt.savefig(RESULTS / 'nb01_image_properties.png', dpi=110, bbox_inches='tight')
plt.show()'''


INTEGRITY = r'''# Full pass over every file: decode it once and get three things at once —
# whether it opens at all, its md5 (exact duplicates) and a perceptual hash
# (near-duplicates: the same painting rescaled or re-encoded).
#
# The perceptual key is 128 bits: an 8x8 average hash *and* an 8x8 difference
# hash, and both must match. The average hash alone is not safe on this dataset —
# it is nearly degenerate for low-contrast work such as engravings and pen
# drawings, so whole classes of genuinely different pictures collide on it. The
# difference hash encodes horizontal gradients instead of absolute brightness,
# and two unrelated paintings agreeing on both is implausible.
#
# Duplicates matter here beyond tidiness: two folders of the same artist were
# merged above, so the same painting really can be present twice.
import hashlib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO


def inspect(path):
    try:
        raw = path.read_bytes()
        with Image.open(BytesIO(raw)) as im:
            gray = im.convert('L')
            avg = np.asarray(gray.resize((8, 8), Image.BILINEAR), dtype=np.float32)
            diff = np.asarray(gray.resize((9, 8), Image.BILINEAR), dtype=np.float32)
        bits = np.concatenate([(avg > avg.mean()).flatten(),
                               (diff[:, 1:] > diff[:, :-1]).flatten()])
        phash = ''.join('1' if b else '0' for b in bits)
        return path, hashlib.md5(raw).hexdigest(), phash, None
    except Exception as exc:
        return path, None, None, f'{type(exc).__name__}: {exc}'


t0 = time.time()
with ThreadPoolExecutor(max_workers=8) as pool:
    inspected = list(pool.map(inspect, all_files))
print(f'перевірено {len(inspected)} файлів за {time.time() - t0:.0f} с')

corrupt = [(p, err) for p, _, _, err in inspected if err]
print(f'\nбитих / нечитаних: {len(corrupt)}')
for p, err in corrupt[:10]:
    print(f'  {p.parent.name}/{p.name}: {err}')

by_md5, by_phash = {}, {}
exact_dupes, near_dupes = [], []
for path, md5, phash, err in inspected:
    if err:
        continue
    if md5 in by_md5:
        exact_dupes.append((path, by_md5[md5]))
    else:
        by_md5[md5] = path
        if phash in by_phash:
            near_dupes.append((path, by_phash[phash]))
        else:
            by_phash[phash] = path

print(f'точних дублікатів (md5)            : {len(exact_dupes)}')
print(f'візуальних дублікатів (aHash+dHash): {len(near_dupes)}')
for a, b in (exact_dupes + near_dupes)[:10]:
    print(f'  {a.parent.name}/{a.name}  ==  {b.parent.name}/{b.name}')

DROP = {p for p, _ in corrupt} | {p for p, _ in exact_dupes} | {p for p, _ in near_dupes}
clean_files = [p for p in all_files if p not in DROP]
print(f'\nвідкинуто {len(DROP)} файлів, лишилось {len(clean_files)} з {len(all_files)}')

# Очищення не має права вимивати цілий клас. Якщо якийсь клас утратив помітну
# частку робіт, це майже напевно хибні спрацювання, а не справжні дублікати.
if DROP:
    dropped_by_class = pd.Series([CLASS_OF[p.parent.name] for p in DROP]).value_counts()
    total_by_class = pd.Series([CLASS_OF[p.parent.name] for p in all_files]).value_counts()
    share = (dropped_by_class / total_by_class).dropna()
    heavy = share[share > 0.2].sort_values(ascending=False)
    if len(heavy):
        print('\n!! класи, що втратили понад 20 % файлів — перевірте вручну:')
        for class_name, value in heavy.items():
            print(f'   {class_name}: {value:.0%} ({int(dropped_by_class[class_name])} файлів)')

clean_counts = (pd.Series([CLASS_OF[p.parent.name] for p in clean_files])
                .value_counts().rename('n_clean'))
counts = counts.join(clean_counts, on='class')
counts['n_clean'] = counts['n_clean'].fillna(0).astype(int)
counts = counts.sort_values('n_clean', ascending=False).reset_index(drop=True)

# Клас, у якому після очищення лишилось менше трьох зображень, неможливо
# розділити на навчальну, перевірочну й тестову вибірки — такий клас вибуває.
MIN_PER_CLASS = 3
too_small = counts[counts['n_clean'] < MIN_PER_CLASS]
if len(too_small):
    print(f'\nкласів з менш ніж {MIN_PER_CLASS} зображеннями: {len(too_small)} — викидаю')
    print(too_small[['artist', 'n_files', 'n_clean']].to_string(index=False))
    counts = counts[counts['n_clean'] >= MIN_PER_CLASS].reset_index(drop=True)

KEEP_CLASSES = set(counts['class'])
clean_files = [p for p in clean_files if CLASS_OF[p.parent.name] in KEEP_CLASSES]
CLEAN_BY_CLASS = {}
for p in clean_files:
    CLEAN_BY_CLASS.setdefault(CLASS_OF[p.parent.name], []).append(p)

print(f'\nкласів для навчання: {len(counts)}, зображень: {len(clean_files)}')
print(f"дисбаланс після очищення: від {counts['n_clean'].min()} "
      f"до {counts['n_clean'].max()}, "
      f"відношення {counts['n_clean'].max() / counts['n_clean'].min():.1f}:1")'''


SAMPLES = r'''# A look at the actual paintings: four per artist for six artists, picked
# deterministically so the grid is the same on every run.
show_classes = list(counts['class'][:3]) + list(counts['class'][-3:])
fig, axes = plt.subplots(len(show_classes), 4, figsize=(11, 2.7 * len(show_classes)))
for row, class_name in enumerate(show_classes):
    paths = sorted(CLEAN_BY_CLASS[class_name])[:4]
    n_show = int(counts.loc[counts['class'] == class_name, 'n_clean'].iloc[0])
    for col in range(4):
        ax = axes[row, col]
        ax.axis('off')
        if col < len(paths):
            with Image.open(paths[col]) as im:
                ax.imshow(im.convert('RGB'))
        if col == 0:
            ax.set_title(f'{class_name} — {n_show} зображень', fontsize=9, loc='left')
fig.suptitle('Приклади класів: три найчисленніші й три найрідкісніші художники',
             fontsize=12)
plt.tight_layout()
plt.savefig(RESULTS / 'nb01_class_samples.png', dpi=110, bbox_inches='tight')
plt.show()'''


SELECT = r'''# Two tracks out of one dataset.
#
# The main track takes the 15 artists with the most paintings: with a couple of
# dozen images in the rarest class a 50-way model cannot be judged fairly, and
# the report needs a confusion matrix that says something. The full-set run
# stays as a stress test with class weights, so the imbalance is studied rather
# than hidden.
TOP_N = 15
top = counts.head(TOP_N)
TOP15_CLASSES = list(top['class'])
THRESHOLD = int(top['n_clean'].min())

print(f'основний трек: {TOP_N} художників, поріг {THRESHOLD} зображень на клас')
print(top[['artist', 'n_clean', 'genre', 'nationality']].to_string(index=False))
print(f"\nзображень у треку top-15: {int(top['n_clean'].sum())} "
      f"({top['n_clean'].sum() / counts['n_clean'].sum():.0%} від усього набору)")
print(f"дисбаланс усередині треку: {top['n_clean'].max() / top['n_clean'].min():.1f}:1 "
      f"(у всьому наборі {counts['n_clean'].max() / counts['n_clean'].min():.1f}:1)")'''


SPLIT = r'''# Stratified 70/15/15 split with a fixed seed: the proportions of every class
# are preserved in all three subsets, which matters exactly because the dataset
# is imbalanced. The test subset is set aside here and touched only in notebook 04.
#
# Destination file names are decided here too. Two folders of the same artist
# were merged, so two source files can share a stem; without the counter below
# one would silently overwrite the other.
TRAIN_FRAC, VAL_FRAC = 0.70, 0.15
split_rng = np.random.default_rng(SEED)

manifest = []
for class_name in counts['class']:
    paths = sorted(CLEAN_BY_CLASS[class_name])
    idx = split_rng.permutation(len(paths))
    n_train = int(round(len(paths) * TRAIN_FRAC))
    n_val = int(round(len(paths) * VAL_FRAC))
    # Guarantee at least one image per subset even for the rarest artists.
    n_train = min(max(n_train, 1), max(len(paths) - 2, 1))
    n_val = min(max(n_val, 1), max(len(paths) - n_train - 1, 1))

    used_names = {}
    for rank, i in enumerate(idx):
        split = 'train' if rank < n_train else ('val' if rank < n_train + n_val else 'test')
        stem = paths[i].stem
        seen = used_names.get(stem, 0)
        used_names[stem] = seen + 1
        manifest.append({'path': str(paths[i]), 'class': class_name, 'split': split,
                         'dst': f'{stem}.jpg' if not seen else f'{stem}__{seen + 1}.jpg',
                         'in_top15': class_name in TOP15_CLASSES})

manifest = pd.DataFrame(manifest)
assert manifest['path'].is_unique, 'один файл потрапив у вибірку двічі'
assert manifest.groupby(['class', 'dst']).size().max() == 1, \
    'два файли претендують на одне й те саме ім\'я'
assert manifest.groupby('class')['split'].nunique().min() == 3, \
    'є клас, у якого заповнені не всі три вибірки'

print(f'розмір вибірок (усі {len(counts)} класів):')
print(manifest['split'].value_counts().reindex(['train', 'val', 'test']).to_string())
print('\nрозмір вибірок (трек top-15):')
print(manifest[manifest['in_top15']]['split'].value_counts()
      .reindex(['train', 'val', 'test']).to_string())

per_class = (manifest[manifest['in_top15']]
             .pivot_table(index='class', columns='split', values='path',
                          aggfunc='count', fill_value=0)
             .reindex(columns=['train', 'val', 'test'])
             .loc[TOP15_CLASSES])
print('\nпо класах у треку top-15:')
print(per_class.to_string())'''


MATERIALIZE = r'''# Build the folder tree the whole project trains from:
#   dataset/<split>/<artist>/<file>.jpg
#
# Preprocessing done once, here, instead of on every epoch in every notebook:
#   EXIF orientation applied, converted to RGB, short side scaled to 320 px
#   (enough for inputs up to 300x300), re-encoded as JPEG q=90.
# Folder names come from the canonical artist name, so the two source spellings
# of the same artist end up in one directory.
from PIL import ImageOps

DATASET_DIR = Path('/content/dataset') if IN_COLAB else PROJECT_ROOT / 'data' / 'dataset'
TARGET_SHORT_SIDE = 320

if DATASET_DIR.exists():
    shutil.rmtree(DATASET_DIR)

CLASS_DIR = {c: unicodedata.normalize('NFC', c).replace(' ', '_')
             for c in counts['class']}
assert len(set(CLASS_DIR.values())) == len(CLASS_DIR), 'дві назви тек збіглися'

for split in ('train', 'val', 'test'):
    for class_dir in CLASS_DIR.values():
        (DATASET_DIR / split / class_dir).mkdir(parents=True, exist_ok=True)


def prepare_one(record):
    src = Path(record['path'])
    dst = DATASET_DIR / record['split'] / CLASS_DIR[record['class']] / record['dst']
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert('RGB')
        scale = TARGET_SHORT_SIDE / min(im.size)
        if scale < 1:
            im = im.resize((max(round(im.width * scale), 1),
                            max(round(im.height * scale), 1)), Image.LANCZOS)
        im.save(dst, 'JPEG', quality=90)
    return dst


t0 = time.time()
with ThreadPoolExecutor(max_workers=8) as pool:
    written = list(pool.map(prepare_one, manifest.to_dict('records')))
print(f'підготовлено {len(written)} зображень за {time.time() - t0:.0f} с')

ALL_CLASSES = sorted(CLASS_DIR.values())
TOP15 = [CLASS_DIR[c] for c in TOP15_CLASSES]

n_written = sum(1 for _ in DATASET_DIR.rglob('*.jpg'))
assert n_written == len(manifest), \
    f'записано {n_written}, а в маніфесті {len(manifest)} — частина файлів перезаписалась'

total_mb = sum(p.stat().st_size for p in DATASET_DIR.rglob('*.jpg')) / 1e6
print(f'дерево: {DATASET_DIR} ({total_mb:.0f} МБ)')
for split in ('train', 'val', 'test'):
    n_all = sum(1 for _ in (DATASET_DIR / split).rglob('*.jpg'))
    n_top = sum(len(list((DATASET_DIR / split / c).glob('*.jpg'))) for c in TOP15)
    print(f'  {split:<6} усі {len(ALL_CLASSES)}: {n_all:>6} | top-15: {n_top:>6}')'''


EXPORT_PREPARED = r'''# Ship the prepared tree to Drive once. Notebooks 02-04 pull this zip in about
# a minute instead of unpacking the 2.4 GB original every session.
# JPEGs are already compressed, so ZIP_STORED is used: same size, much faster.
PREPARED = DRIVE_DIR / 'prepared'
PREPARED.mkdir(parents=True, exist_ok=True)

local_zip = PROJECT_ROOT / 'dataset.zip'
t0 = time.time()
with zipfile.ZipFile(local_zip, 'w', zipfile.ZIP_STORED) as z:
    for f in sorted(DATASET_DIR.rglob('*.jpg')):
        z.write(f, f.relative_to(DATASET_DIR))
print(f'зіп зібрано за {time.time() - t0:.0f} с, '
      f'{local_zip.stat().st_size / 1e6:.0f} МБ')

t0 = time.time()
shutil.copy(local_zip, PREPARED / 'dataset.zip')
print(f'скопійовано на Drive за {time.time() - t0:.0f} с')

(PREPARED / 'class_names.json').write_text(
    json.dumps({'all50': ALL_CLASSES, 'top15': TOP15,
                'display': {CLASS_DIR[c]: c for c in counts['class']}},
               ensure_ascii=False, indent=2), encoding='utf-8')
manifest.to_csv(PREPARED / 'splits_manifest.csv', index=False, encoding='utf-8')
counts.to_csv(PREPARED / 'class_counts.csv', index=False, encoding='utf-8')
print('записано class_names.json, splits_manifest.csv, class_counts.csv')'''


EXPORT_01 = r'''# Numbers for the dataset section of the report.
payload = {
    'notebook': 'nb01',
    'source': 'https://www.kaggle.com/datasets/ikarus777/best-artworks-of-all-time',
    'archive': ARCHIVE_NAME,
    'n_folders': int(len(folders)),
    'n_classes_total': int(len(counts)),
    'merged_classes': {c: names for c, names in split_classes.items()},
    'n_images_raw': int(TOTAL_IMAGES),
    'n_images_clean': int(len(clean_files)),
    'n_corrupt': int(len(corrupt)),
    'n_exact_duplicates': int(len(exact_dupes)),
    'n_near_duplicates': int(len(near_dupes)),
    'names_fixed_by_normalisation': [list(pair) for pair in differing],
    'names_fixed_by_similarity': [[a, b, round(r, 3)] for a, b, r in fuzzy_matched],
    'unmatched_folders': unmatched_folders,
    'imbalance_ratio_all': float(counts['n_clean'].max() / counts['n_clean'].min()),
    'top15_threshold': int(THRESHOLD),
    'top15': TOP15,
    'split_fractions': {'train': TRAIN_FRAC, 'val': VAL_FRAC,
                        'test': round(1 - TRAIN_FRAC - VAL_FRAC, 2)},
    'split_sizes_all': manifest['split'].value_counts().to_dict(),
    'split_sizes_top15': manifest[manifest['in_top15']]['split'].value_counts().to_dict(),
    'target_short_side': TARGET_SHORT_SIDE,
    # class_dir — ім'я теки, тобто рівно те, що лежить у TOP15 і ALL_CLASSES.
    'class_counts': counts.assign(
        class_dir=counts['class'].map(CLASS_DIR))[
            ['artist', 'class', 'class_dir', 'n_folders', 'n_files', 'n_clean',
             'genre', 'nationality']].to_dict('records'),
}
out = RESULTS / 'raw' / 'nb01.json'
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
print('записано', out)

zip_path = PROJECT_ROOT / 'project_nb01_results.zip'
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted(RESULTS.rglob('*')):
        if f.is_file() and f.suffix in ('.json', '.png', '.csv', '.md'):
            z.write(f, f.relative_to(RESULTS))
print('зіп:', zip_path, f'({zip_path.stat().st_size / 1e6:.1f} МБ)')

if IN_COLAB:
    from google.colab import files

    files.download(str(zip_path))'''
