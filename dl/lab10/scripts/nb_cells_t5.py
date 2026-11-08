r"""Розв'язки для базового ноутбука Завдання 5 — Sign Language MNIST.

Заповнюються лише блоки між `### START CODE HERE` і `### END CODE HERE`
у base_notebooks/Lab_10_5_Assignment.ipynb. Решта рядків не змінюється.

Блок у клітинці 4 (завантаження CSV через gdown) викладач уже заповнив, тому
розв'язку для нього тут немає — він лишається як є.
"""

SOLUTIONS = {}

# ---------------------------------------------------------------- розбір CSV
# Умова вимагає вкластися в хвилину. Один виклик np.array на всю таблицю
# розбирає 27455x785 значень приблизно за 6 секунд: перетворення рядків у
# float робиться в C, а не поелементно в Python.
SOLUTIONS["parse_data_from_input"] = '''
    # Use csv.reader, passing in the appropriate delimiter
    # Remember that csv.reader can be iterated and returns one line in each iteration
    csv_reader = csv.reader(file, delimiter=',')

    # Перший рядок — заголовок із назвами колонок, він не є даними.
    next(csv_reader)

    # Кожен рядок: мітка + 784 значення пікселів. Розбираємо всю таблицю
    # одним викликом np.array, інакше поелементне перетворення займе хвилини.
    data = np.array([row for row in csv_reader], dtype='float64')

    labels = data[:, 0]
    images = data[:, 1:].reshape(-1, 28, 28)
'''

# ---------------------------------------------------------------- генератори
# Головна відмінність від попередніх завдань — horizontal_flip тут НЕ можна.
SOLUTIONS["train_val_generators"] = '''
  # In this section you will have to add another dimension to the data
  # So, for example, if your array is (10000, 28, 28)
  # You will need to make it (10000, 28, 28, 1)
  # Hint: np.expand_dims
  training_images = np.expand_dims(training_images, axis=-1)
  validation_images = np.expand_dims(validation_images, axis=-1)

  # Instantiate the ImageDataGenerator class
  # Don't forget to normalize pixel values
  # and set arguments to augment the images (if desired)
  #
  # Аугментація тут навмисно слабка і БЕЗ horizontal_flip: дзеркальне
  # відображення жесту дає жест іншої руки, а для деяких літер — взагалі
  # іншу літеру. Для котів і собак віддзеркалення нешкідливе, для мови
  # жестів воно псує мітку.
  #
  # Межі підібрані вимірюванням, двома повними прогонами по 15 епох:
  #
  #   поворот 15, зсув 0.1, зсув кута 0.1, зум 0.1 -> train 0.9846, val 0.9971
  #   поворот 10, зсув 0.05,               зум 0.05 -> train 0.9924, val 0.9812
  #
  # Точність на навчанні рахується на аугментованих зображеннях, тому при
  # сильних спотвореннях вона виходить НИЖЧОЮ за перевірочну і не дотягує до
  # орієнтира 0.99. Слабші спотворення піднімають її вище порога, трохи
  # віддаючи перевірочну; обидва орієнтири (>0.99 і >0.95) при цьому виконані.
  train_datagen = ImageDataGenerator(rescale=1./255,
                                     rotation_range=10,
                                     width_shift_range=0.05,
                                     height_shift_range=0.05,
                                     zoom_range=0.05,
                                     fill_mode='nearest')


  # Pass in the appropriate arguments to the flow method
  train_generator = train_datagen.flow(x=training_images,
                                       y=training_labels,
                                       batch_size=32)


  # Instantiate the ImageDataGenerator class (don't forget to set the rescale argument)
  # Remember that validation data should not be augmented
  validation_datagen = ImageDataGenerator(rescale=1./255)

  # Pass in the appropriate arguments to the flow method
  validation_generator = validation_datagen.flow(x=validation_images,
                                                 y=validation_labels,
                                                 batch_size=32)
'''

# ---------------------------------------------------------------- модель
# Обмеження умови: не більше 2 Conv2D і 2 MaxPooling2D.
#
# Вихідних нейронів 25, а не 26. Мітки в наборі йдуть від 0 (A) до 24 (Y):
# літери J і Z вимагають руху руки, тож статичних кадрів для них немає.
# Оскільки найбільша мітка — 24, шару потрібно рівно 25 виходів.
#
# Мітки — цілі числа, а не one-hot, тому функція втрат
# sparse_categorical_crossentropy, а не categorical_crossentropy.
SOLUTIONS["create_model"] = '''
  # Define the model
  # Use no more than 2 Conv2D and 2 MaxPooling2D
  model = tf.keras.models.Sequential([
      tf.keras.layers.Input(shape=(28, 28, 1)),
      tf.keras.layers.Conv2D(64, (3, 3), activation='relu'),
      tf.keras.layers.MaxPooling2D(2, 2),
      tf.keras.layers.Conv2D(64, (3, 3), activation='relu'),
      tf.keras.layers.MaxPooling2D(2, 2),
      tf.keras.layers.Flatten(),
      tf.keras.layers.Dropout(0.2),
      tf.keras.layers.Dense(512, activation='relu'),
      tf.keras.layers.Dense(25, activation='softmax')
  ])


  model.compile(optimizer = 'adam',
                loss = 'sparse_categorical_crossentropy',
                metrics=['accuracy'])
'''
