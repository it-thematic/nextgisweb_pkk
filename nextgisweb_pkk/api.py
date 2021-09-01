# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import json

from nextgisweb import geojson
from nextgisweb.env import env
from nextgisweb.lib.geometry import Geometry, Transformer
from nextgisweb.resource import resource_factory, Resource
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
    for feature in data:
        feature = feature['feature']
        feature_attr = feature['attrs']
        feature_extent = feature.get('extent', None) or dict()
        result.append(dict(
            typeobj=feature.get('type'),
            numbpkk=feature_attr.get('cn'),
            categorypkk=value_from_xsd('dCategories_v01.xsd', feature_attr.get('category_type', None)),
            typepkk=value_from_xsd('dAllowedUse_v02.xsd', feature_attr.get('util_code', None)),
            typepkk_bydoc=feature_attr.get('util_by_doc', None),
            adresspkk=feature_attr.get('address', None),
            squarepkk=feature_attr.get('area_value'),
            costpkk=feature_attr.get('cad_cost'),
            datepkk=feature_attr.get('cc_date_entering'),
            statuspkk=value_from_xsd('dStates_v01.xsd', feature_attr.get('statecd', None)),
            box=[
                    feature_extent.get('xmin', None), feature_extent.get('ymin', None),
                    feature_extent.get('xmax', None), feature_extent.get('ymax', None)
            ]
        ))
    result.sort(key=lambda x: [int(i) if i.isdigit() else i for i in x['numbpkk'].split(':')])
    return result


def _make_request_to_aiorosreestr(search):
    host = env.pkk.options['host']
    session = get_session('pkk', host, None, None)
    if host.endswith('/'):
        host = host[:-1]

    result = session.get(url=host + '/features/',
                         params=dict(search=search)
                         )
    if result.status_code == 200:
        return result.json()
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


def pkk_search(request):
    headers = dict()
    headers[str('Content-Type')] = str('application/json')

    like = request.params.get('like', '')
    if not like:
        return Response(json.dumps(dict(), cls=geojson.Encoder))

    result = _make_request_to_aiorosreestr(like)
    result = _build_pkk_data(result)
    return Response(json.dumps(result, cls=geojson.Encoder), headers=headers)


def setup_pyramid(comp, config):
    config.add_tween('nextgisweb_pkk.api.pkk_tween_factory', under=(
        'nextgisweb.pyramid.api.cors_tween_factory',
        'INGRESS'))

    config.add_route(
        'pkk.search', '/api/pkk/search/') \
        .add_view(pkk_search, request_method='GET')
