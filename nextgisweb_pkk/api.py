# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import json

from nextgisweb import geojson
from nextgisweb.env import env
from nextgisweb.lib.geometry import Geometry, Transformer
from nextgisweb.spatial_ref_sys import SRS
from nextgisweb.tmsclient.session_keeper import get_session
from nextgisweb.webmap.model import WebMap, WebMapScope
from nextgisweb.webmap.util import get_recursive_values
from pyramid.response import Response

from nextgisweb_pkk.xds import value_from_xsd

# =================================================================================================================== #
# numbpkk       string		кадастровый номер участка
# categorypkk	string		категория земель
# typepkk	    string		вид разрешенного использования
# adresspkk	    string		адрес
# squarepkk	    real		декларированная площадь
# costpkk	    money		кадастровая стоимость
# datepkk	    date		дата постановки на учет
# statuspkk	    string		статус земельного участка
# =================================================================================================================== #


def _build_pkk_data(data):
    result = []
    for feature_coll in data:
        feature_type = feature_coll['type']
        features = feature_coll['features'] if feature_type == "FeatureCollection" else [feature_coll]
        for feature in features:
            feature_attr = feature['properties']
            feature_geometry = feature.get('geometry', None)
            geom = None
            if feature_geometry:
                geom_4326 = Geometry.from_geojson(feature_geometry, srid=4326)
                srs_3857 = SRS.filter_by(id=3857).one()
                srs_4326 = SRS.filter_by(id=4326).one()
                transformer = Transformer(srs_4326.wkt, srs_3857.wkt)
                geom = transformer.transform(geom_4326)

            result.append(dict(
                typeobj=feature_attr.get('type'),
                numbpkk=feature_attr.get('cn'),
                categorypkk=value_from_xsd('dCategories_v01.xsd', feature_attr.get('category_type', None)) or "Не определено",
                typepkk=value_from_xsd('dUtilizations_v01.xsd', feature_attr.get('util_code', None)) or "Не определено",
                typepkk_bydoc=feature_attr.get('util_by_doc', None),
                adresspkk=feature_attr.get('address', None),
                squarepkk=feature_attr.get('area_value'),
                costpkk=feature_attr.get('cad_cost'),
                datepkk=feature_attr.get('cc_date_entering'),
                statuspkk=value_from_xsd('dStates_v01.xsd', feature_attr.get('statecd', None)),
                box=[None, None, None, None],
                geometry=None
            ))
            if geom:
                result[-1]['geometry'] = geom.wkt
                result[-1]['box'] = list(geom.bounds)

    result.sort(key=lambda x: [int(i) if i.isdigit() else i for i in x['numbpkk'].split(':')])
    return result


def _make_request_to_aiorosreestr(search, **kwargs):
    host = env.pkk.options['host']
    session = get_session('pkk', host, None, None)
    if host.endswith('/'):
        host = host[:-1]

    try:
        result = session.get(url=host + '/features/',
                             params=dict(search=search, **kwargs)
                             )
    except Exception as e:
        return []
    if result.status_code == 200:
        return result.json()
    env.pkk.logger.error(result.text)
    return []


def _add_preview_link(request):
    """"""
    base_map_id = request.env.webmap.options.get('base_map', None)
    if base_map_id is None:
        base_map = WebMap.query().first()
    else:
        base_map = WebMap.filter_by(id=int(base_map_id)).first()
    if not base_map.has_permission(WebMapScope.display, request.user):
        return None
    layers_ids = get_recursive_values(base_map)
    layers_ids_str = ','.join(str(_id) for _id in layers_ids)
    return request.route_url('render.image') + '?resource=' + layers_ids_str


def pkk_tween_factory(handler, registry):
    """ Tween adds integration with aiorosreestr """

    def pkk_tween(request):
        # Only request under /api/ and /feature/{id} are handled
        is_api = '/api/' in request.path_info
        is_feature = '/feature/' in request.path_info and request.path_info.rsplit('/', 1)[-1].isalnum()
        include_pkk = request.GET.get('pkk', 'no') in ('true', 'yes', '1')

        if not is_api or not is_feature or request.method != 'GET' or not include_pkk:
            # Run default request handler
            return handler(request)

        def make_aiorosreestr_request(request, response):
            if 400 <= response.status_code:
                return
            feat = response.json
            feat_geometry_3857 = Geometry.from_wkt(feat['geom'])
            srs_from = SRS.filter_by(id=3857).one()
            srs_to = SRS.filter_by(id=4326).one()
            transformer = Transformer(srs_from.wkt, srs_to.wkt)
            feat_geometry_4326 = transformer.transform(feat_geometry_3857)
            result = _make_request_to_aiorosreestr(json.dumps(feat_geometry_4326.to_geojson()))
            response_json = response.json
            response_json['fields']['rosreestr'] = _build_pkk_data(result)
            response_json['preview'] = _add_preview_link(request) + '&extent=' + ','.join(str(_item) for _item in feat_geometry_3857.bounds)
            response.json_body = response_json
            env.pkk.logger.info(response_json['fields']['rosreestr'])

        request.add_response_callback(make_aiorosreestr_request)
        # Run default request handler
        return handler(request)

    return pkk_tween


def _transform_geom(obj):
    _crs = obj.get('crs', dict())
    _crs_prop = _crs.get('properties', dict())
    _crs_srs = _crs_prop.get('name', '')
    _crs_code = _crs_srs.split(':')[-1] or 4326
    geom_srs = Geometry.from_geojson(obj, srid=int(_crs_code))
    srs_from = SRS.filter_by(id=geom_srs.srid).one()
    srs_to = SRS.filter_by(id=4326).one()
    transformer = Transformer(srs_from.wkt, srs_to.wkt)
    return transformer.transform(geom_srs).to_geojson()


def _pkk_search(like):
    if not like:
        return dict()

    if isinstance(like, dict):
        _search = json.dumps(_transform_geom(like))
    else:
        try:
            _search = json.loads(like)
        except json.JSONDecodeError:
            _search = like
        else:
            _search = json.dumps(_transform_geom(_search))
    result = _make_request_to_aiorosreestr(_search, center_only=False)
    return _build_pkk_data(result)


def pkk_gsearch(request):
    headers = dict()
    headers['Content-Type'] = 'application/json'

    like = request.params.get('like', '')
    result = _pkk_search(like)
    return Response(json.dumps(result, cls=geojson.Encoder), headers=headers)


def pkk_psearch(request):
    headers = dict()
    headers['Content-Type'] = 'application/json'

    body = request.json_body
    like = body.get('like')
    result = _pkk_search(like)
    return Response(json.dumps(result, cls=geojson.Encoder), headers=headers)


def setup_pyramid(comp, config):
    config.add_tween('nextgisweb_pkk.api.pkk_tween_factory', under=(
        'nextgisweb.pyramid.api.cors_tween_factory',
        'INGRESS'))

    config.add_route(
        'pkk.search', '/api/pkk/search/') \
        .add_view(pkk_gsearch, request_method='GET') \
        .add_view(pkk_psearch, request_method='POST')
