# create and train the prediction model

import tensorflow as tf
import pandas as pd
import numpy as np
import sklearn
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

data = pd.read_csv('sports.csv')
qualifier = 'result' #Whatever works ig
x = data.drop(qualifier, axis = 1).values
y = data[qualifier].values

scaler = StandardScaler()
x = scaler.fit_transform(x)

train_split = int(len(x) * 0.8)
x_train, x_test, y_train, y_test = x[:train_split], x[train_split:], y[:train_split], y[train_split:]

model = tf.keras.models.Sequential([
  tf.keras.layers.Dense(64, activation='relu'),
  tf.keras.layers.Dropout(0.3),
  tf.keras.layers.Dense(32, activation='softmax'),
  tf.keras.layers.Dropout(0.2),
  tf.keras.layers.Dense(2, activation="relu")
])

model.compile(optimizer='adam',
  loss='sparse_categorical_crossentropy',
  metrics=['accuracy'])

model.fit(x_train, y_train, epochs = 25, batch_size = 32, validation_split = 0.1)
test_loss, test_accuracy = model.evaluate(x_test, y_test)
print(f'Accuracy of model is {test_accuracy:.4f}')

