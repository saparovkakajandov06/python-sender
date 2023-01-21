import base64
import json
import logging
import os
import sys
import pathlib
from PIL import Image
import pika
import string
import random
import sqlite3

from logger import setup_logger

logger = logging.getLogger("queues")

USER = str(os.getenv('RABBITMQ_USER'))
PASSWORD = str(os.getenv('RABBITMQ_PASSWORD'))
HOST = str(os.getenv('RABBITMQ_HOST'))
PORT = int(os.getenv('RABBITMQ_PORT'))
CONSUME_QUEUE = str(os.getenv('RABBITMQ_PRODUCT_QUEUE'))
PRODUCE_QUEUE = str(os.getenv('RABBITMQ_CONSUME_QUEUE'))
IMAGES_DB = str(os.getenv('IMAGES_DB'))
IMAGES_PATH = str(os.getenv('IMAGES_FOLDER'))

credentials = pika.PlainCredentials(USER, PASSWORD)
conn_params = pika.ConnectionParameters(host=HOST, port=PORT, credentials=credentials)


# database

db = sqlite3.connect(IMAGES_DB, timeout=1)
cur = db.cursor()


def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))

def send_image(imagebinary, ch):
    image = base64.b64encode(imagebinary)
    photo_id = id_generator()
    logger.info('Start send result')
    data = {
        "photo_id": photo_id,
        "image": str(image),
    }
    message = json.dumps(data)
    logger.debug('sending:', message)
    ch.basic_publish(exchange='',
                     routing_key=PRODUCE_QUEUE,
                     body=message,
                     properties=pika.BasicProperties(
                         delivery_mode=2,  # make message persistent
                     ))
    logger.info('End send result')


def main():
    connection = pika.BlockingConnection(conn_params)

    channel = connection.channel()

    def callback(ch, method, properties, body):
        try:
            data = json.loads(body)
            logger.debug('Got response:', data)
            photo_id = data['photo_id']
            label = data['label']

            logger.info(f'Predict label for image: {photo_id} is {label}')
            # write to sqlite
            create_com=f"INSERT INTO responses VALUES(\'{photo_id}\', \'{label}\')"
            try:
                cur.execute(create_com)
            except sqlite3.OperationalError as e:
                logger.error("error: ", str(e))
            
            

            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.exception('Error', e)
            # https://stackoverflow.com/questions/24333840/rejecting-and-requeueing-a-rabbitmq-task-when-prefetch-count-1
            ch.basic_reject(delivery_tag=method.delivery_tag, requeue=True)

    channel.basic_consume(queue=CONSUME_QUEUE, on_message_callback=callback)

    logger.info('Waiting for messages. To exit press CTRL+C')

    # read images from filesystem
    
    images_array = []
    for (root, dirs, file) in os.walk(IMAGES_PATH):
        for f in file:
            if '.jpg' or '.png' in f:
                images_array.append(f)

    for image in images_array:
        imagebinary = open(IMAGES_PATH+'/'+image, 'rb')
        send_image(imagebinary.read(), channel)

    channel.start_consuming()

if __name__ == '__main__':
    try:
        setup_logger()
        main()
    except KeyboardInterrupt:
        print('Interrupted')
        sys.exit(0)
