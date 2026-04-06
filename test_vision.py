from google.cloud import vision

client = vision.ImageAnnotatorClient()

path = "IMG20260302042340.jpg"

with open(path, "rb") as f:
    content = f.read()

image = vision.Image(content=content)
response = client.text_detection(image=image)

if response.error.message:
    raise RuntimeError(response.error.message)

if response.text_annotations:
    print(response.text_annotations[0].description)
else:
    print("NO_TEXT")