from flask import Blueprint, Response, abort
from ..models import UploadedImage

media_bp = Blueprint('media', __name__)


@media_bp.route('/media/<int:image_id>')
def serve_image(image_id):
    image = UploadedImage.query.get(image_id)
    if not image:
        abort(404)
    response = Response(image.data, mimetype=image.mime_type)
    # Cache largo: cada subida nueva genera un id nuevo (no se pisa el mismo id),
    # así que es seguro cachear agresivo sin riesgo de mostrar una imagen vieja.
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response
