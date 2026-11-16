r"""Клітинки ноутбука 03 — перенесення навчання й тонке налаштування.

Другий підхід із тих, що умова просить порівняти: попередньо навчені на ImageNet
мережі замість навчання з нуля. Три бекбони, три глибини донавчання, зважування
класів і стрес-тест на всіх 50 класах.
"""

MIXED = r'''# Mixed precision: half-precision activations, float32 weights and loss scaling.
# Roughly doubles throughput on L4/A100 and costs nothing in accuracy, which is
# what makes a series of eleven experiments fit into one session.
# The last layer is forced back to float32 so softmax stays numerically stable.
if tf.config.list_physical_devices('GPU'):
    keras.mixed_precision.set_global_policy('mixed_float16')
print('політика точності:', keras.mixed_precision.global_policy().name)'''


BUILD = r'''# Transfer learning: an ImageNet backbone with its own head replaced.
#
# Each network expects its own input range, and getting this wrong costs accuracy
# silently, without raising anything. MobileNetV2 and ResNet50V2 want [-1, 1];
# EfficientNet keeps its normalisation inside the model and must be fed raw
# [0, 255]. The conversion is expressed as a Rescaling layer rather than a Lambda
# wrapping preprocess_input, so the saved .keras file reloads in notebook 04
# without custom objects or safe_mode=False.
BACKBONES = {
    'MobileNetV2': keras.applications.MobileNetV2,
    'EfficientNetB0': keras.applications.EfficientNetB0,
    'ResNet50V2': keras.applications.ResNet50V2,
    'EfficientNetB3': keras.applications.EfficientNetB3,
}


def preprocess_layer(backbone):
    if backbone.startswith('EfficientNet'):
        return None
    return keras.layers.Rescaling(1. / 127.5, offset=-1, name='preprocess')


def make_optimizer(cfg, steps_per_epoch=None):
    lr = cfg.get('lr', 1e-3)
    if cfg.get('schedule') == 'cosine' and steps_per_epoch:
        lr = keras.optimizers.schedules.CosineDecay(
            initial_learning_rate=lr,
            decay_steps=steps_per_epoch * cfg.get('epochs', 20))
    name = cfg.get('optimizer', 'adam')
    if name == 'adam':
        return keras.optimizers.Adam(learning_rate=lr)
    if name == 'rmsprop':
        return keras.optimizers.RMSprop(learning_rate=lr)
    if name == 'sgd':
        return keras.optimizers.SGD(learning_rate=lr, momentum=0.9)
    raise ValueError(f'невідомий оптимізатор: {name}')


def compile_model(model, cfg, classes):
    steps = -(-count_steps(classes) // cfg.get('batch', 32))
    model.compile(optimizer=make_optimizer(cfg, steps),
                  loss='sparse_categorical_crossentropy',
                  metrics=['accuracy'])
    return model


def find_backbone(model):
    """The nested pretrained model inside ours (the augment block is Sequential)."""
    for layer in model.layers:
        if isinstance(layer, keras.Model) and not isinstance(layer, keras.Sequential):
            return layer
    raise LookupError('у моделі немає вкладеного бекбона')


def unfreeze(base, fraction):
    """Unfreeze the last `fraction` of the backbone's layers.

    BatchNorm layers stay frozen regardless: they carry ImageNet running
    statistics, and letting mini-batches of 32 paintings rewrite them is the
    classic way to make fine-tuning diverge.
    """
    base.trainable = True
    cutoff = int(len(base.layers) * (1 - fraction))
    for layer in base.layers[:cutoff]:
        layer.trainable = False
    for layer in base.layers:
        if isinstance(layer, keras.layers.BatchNormalization):
            layer.trainable = False
    trainable = sum(1 for l in base.layers if l.trainable)
    print(f'розморожено {trainable} з {len(base.layers)} шарів бекбона')


def build_transfer(cfg, classes):
    # Stage two: continue from a trained frozen model instead of starting over.
    if cfg.get('init_from'):
        src = MODELS_DIR / f"{cfg['init_from']}.keras"
        if not src.exists():
            raise FileNotFoundError(f'немає {src} — спочатку виконайте {cfg["init_from"]}')
        model = keras.models.load_model(src)
        unfreeze(find_backbone(model), cfg.get('unfreeze', 0.2))
        return compile_model(model, cfg, classes)

    size = cfg.get('img_size', 224)
    base = BACKBONES[cfg['backbone']](include_top=False, weights='imagenet',
                                      input_shape=(size, size, 3))
    base.trainable = False

    augment = make_augment(cfg.get('augment'))
    inputs = keras.Input(shape=(size, size, 3))
    x = augment(inputs) if augment is not None else inputs
    pre = preprocess_layer(cfg['backbone'])
    if pre is not None:
        x = pre(x)
    x = base(x, training=False)
    x = keras.layers.GlobalAveragePooling2D()(x)
    x = keras.layers.Dropout(cfg.get('dropout', 0.3))(x)
    outputs = keras.layers.Dense(len(classes), activation='softmax',
                                 dtype='float32')(x)
    model = keras.Model(inputs, outputs, name=cfg['name'])
    return compile_model(model, cfg, classes)


def run_cfg(cfg):
    return run(cfg, build_transfer)


print('доступні бекбони:', ', '.join(BACKBONES))'''


FROZEN = r'''# B1-B3: the same head on three different ImageNet backbones, everything else
# identical. The base is frozen, so this measures how well each network's
# ready-made features already separate painters.
FROZEN_DEFAULTS = {'augment': 'light', 'lr': 1e-3, 'epochs': 20,
                   'dropout': 0.3, 'batch': 32, 'img_size': 224}

for backbone in ('MobileNetV2', 'EfficientNetB0', 'ResNet50V2'):
    run_cfg({**FROZEN_DEFAULTS,
             'name': f'b_frozen_{backbone.lower()}',
             'title': f'{backbone}, заморожена база',
             'backbone': backbone})

FROZEN_RUNS = [f'b_frozen_{b.lower()}'
               for b in ('MobileNetV2', 'EfficientNetB0', 'ResNet50V2')]
BEST_FROZEN = max(FROZEN_RUNS, key=lambda n: results[n]['best_val_accuracy'])
BEST_BACKBONE = results[BEST_FROZEN]['config']['backbone']
print(f'\nнайкращий бекбон: {BEST_BACKBONE} ({BEST_FROZEN})')
print(summary_frame(FROZEN_RUNS).to_string(index=False))'''


AUGMENT_EXP = r'''# B4: the augmentation question, asked against the best frozen model so that
# strength of augmentation is the only thing that changes.
run_cfg({**FROZEN_DEFAULTS, 'backbone': BEST_BACKBONE, 'augment': 'strong',
         'name': 'b4_strong_aug',
         'title': f'{BEST_BACKBONE}, заморожена база, сильна аугментація'})'''


FINETUNE = r'''# B5-B7: how deep to fine-tune. All three continue from the same frozen model,
# so the depth of unfreezing is the only difference between them.
#
# A two-stage protocol is deliberate: unfreezing a backbone while the randomly
# initialised head still produces large gradients destroys the pretrained
# features in the first few steps. The curves below cover stage two only.
run_cfg({**FROZEN_DEFAULTS, 'backbone': BEST_BACKBONE,
         'name': 'b5_ft_20', 'title': 'донавчання останніх 20 % шарів, lr 1e-4',
         'init_from': BEST_FROZEN, 'unfreeze': 0.2, 'lr': 1e-4,
         'epochs': 15, 'patience': 4})

run_cfg({**FROZEN_DEFAULTS, 'backbone': BEST_BACKBONE,
         'name': 'b6_ft_50', 'title': 'донавчання останніх 50 % шарів, lr 5e-5',
         'init_from': BEST_FROZEN, 'unfreeze': 0.5, 'lr': 5e-5,
         'epochs': 15, 'patience': 4})

run_cfg({**FROZEN_DEFAULTS, 'backbone': BEST_BACKBONE,
         'name': 'b7_ft_all_cosine',
         'title': 'донавчання всієї бази, косинусний розклад від 1e-4',
         'init_from': BEST_FROZEN, 'unfreeze': 1.0, 'lr': 1e-4,
         'schedule': 'cosine', 'epochs': 15, 'patience': 5})

FT_RUNS = ['b5_ft_20', 'b6_ft_50', 'b7_ft_all_cosine']
BEST_FT = max(FT_RUNS, key=lambda n: results[n]['best_val_accuracy'])
print(f'\nнайкраща глибина донавчання: {BEST_FT}')
print(summary_frame([BEST_FROZEN] + FT_RUNS).to_string(index=False))'''


IMBALANCE = r'''# B8-B10: the imbalance questions.
#
# B8 repeats the best fine-tuning run with balanced class weights. B9 and B10 are
# the stress test the task asks for — all 50 artists, including the one with
# ~24 paintings, where the rarest classes are exactly what a plain accuracy
# number hides.
best_ft_cfg = dict(results[BEST_FT]['config'])

run_cfg({**best_ft_cfg, 'name': 'b8_class_weight',
         'title': f'{BEST_FT} + зважування класів', 'class_weight': True})

run_cfg({**FROZEN_DEFAULTS, 'backbone': BEST_BACKBONE, 'classes': ALL50,
         'name': 'b9_all50_frozen',
         'title': 'усі 50 класів, заморожена база, зважування класів',
         'class_weight': True, 'epochs': 25})

run_cfg({**FROZEN_DEFAULTS, 'backbone': BEST_BACKBONE, 'classes': ALL50,
         'name': 'b10_all50_ft',
         'title': 'усі 50 класів, донавчання, зважування класів',
         'init_from': 'b9_all50_frozen',
         'unfreeze': results[BEST_FT]['config'].get('unfreeze', 0.2),
         'lr': 5e-5, 'schedule': results[BEST_FT]['config'].get('schedule'),
         'class_weight': True, 'epochs': 15, 'patience': 4})'''


EXTRA = r'''# B11: a bigger backbone at a bigger input, run only if there is time left.
# EfficientNetB3 at 300x300 is about four times the compute of B0 at 224.
RUN_EXTRA = False

if RUN_EXTRA:
    run_cfg({**FROZEN_DEFAULTS, 'backbone': 'EfficientNetB3', 'img_size': 300,
             'batch': 16, 'name': 'b11_effnetb3_300',
             'title': 'EfficientNetB3, вхід 300x300, заморожена база'})
else:
    print('b11 пропущено (RUN_EXTRA = False)')'''


ANALYSIS = r'''# Everything measured so far, including the runs from notebook 02 — they were
# written to the same registry on Drive, so the comparison between "from scratch"
# and "transfer learning" needs no copying of numbers by hand.
transfer_runs = [n for n in results if n.startswith('b')]
scratch_runs = [n for n in results if n.startswith('a')]

print('ПЕРЕНЕСЕННЯ НАВЧАННЯ')
print(summary_frame(transfer_runs).to_string(index=False))

if scratch_runs:
    print('\nМЕРЕЖІ З НУЛЯ (ноутбук 02)')
    print(summary_frame(scratch_runs).to_string(index=False))

    best_scratch = max(scratch_runs, key=lambda n: results[n]['test_accuracy'])
    best_transfer = max([n for n in transfer_runs if results[n]['n_classes'] == len(TOP15)],
                        key=lambda n: results[n]['test_accuracy'])
    gain = results[best_transfer]['test_accuracy'] - results[best_scratch]['test_accuracy']
    print(f'\nнайкраща з нуля    : {best_scratch} — '
          f"{results[best_scratch]['test_accuracy']:.4f}")
    print(f'найкраща з переносом: {best_transfer} — '
          f"{results[best_transfer]['test_accuracy']:.4f}")
    print(f'приріст: {gain:+.4f}')

print('\nдисбаланс: 15 класів проти 50')
for name in ('b9_all50_frozen', 'b10_all50_ft'):
    if name in results:
        r = results[name]
        print(f"  {name}: test {r['test_accuracy']:.4f}, "
              f"top-3 {r['test_top3_accuracy']:.4f} на {r['n_classes']} класах")

summary_frame(list(results)).to_csv(RESULTS / 'raw' / 'nb03_table.csv',
                                    index=False, encoding='utf-8')
BEST_OVERALL = summary_frame(
    [n for n in results if results[n]['n_classes'] == len(TOP15)]
).iloc[0]['експеримент']
(RESULTS / 'raw' / 'best_model.json').write_text(
    json.dumps({'best_top15': BEST_OVERALL,
                'best_all50': 'b10_all50_ft' if 'b10_all50_ft' in results else None},
               ensure_ascii=False, indent=2), encoding='utf-8')
print(f'\nнайкраща модель проєкту: {BEST_OVERALL} — '
      f"test {results[BEST_OVERALL]['test_accuracy']:.4f}")'''


PLOT_CALL = r'''plot_histories(transfer_runs, 'nb03_histories.png',
                'Криві навчання: перенесення навчання й донавчання')'''
