FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Tashkent \
    FACE_MODELS_DIR=/opt/models \
    # OpenCV FFmpeg logi RTSP manzilini (rekvizitlar bilan) chiqarmasin
    OPENCV_FFMPEG_LOGLEVEL=-8 \
    OPENCV_LOG_LEVEL=ERROR \
    OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tzdata libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# OpenCV Zoo modellari: YuNet (yuz topish) va SFace (yuzni tanish)
RUN mkdir -p /opt/models \
    && curl -fsSL -o /opt/models/face_detection_yunet_2023mar.onnx \
       https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
    && curl -fsSL -o /opt/models/face_recognition_sface_2021dec.onnx \
       https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx \
    && echo "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4  /opt/models/face_detection_yunet_2023mar.onnx" | sha256sum -c - \
    && echo "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79  /opt/models/face_recognition_sface_2021dec.onnx" | sha256sum -c -

WORKDIR /srv/app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x /srv/app/entrypoint.sh \
    && DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput \
    && useradd --system --uid 1000 app \
    && chown -R app /srv/app/staticfiles

USER app
ENTRYPOINT ["/srv/app/entrypoint.sh"]
CMD ["web"]
