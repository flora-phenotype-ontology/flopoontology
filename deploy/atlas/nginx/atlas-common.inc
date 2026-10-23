# Shared by the live and staging servers. The state file sets $atlas_root (the release's web
# directory), $atlas_qlever (127.0.0.1:<port> of its QLever container) and $atlas_release.

root $atlas_root;
charset utf-8;
absolute_redirect off;
add_header X-Atlas-Release $atlas_release always;

location = / {
    try_files /index.html =404;
    add_header X-Atlas-Release $atlas_release always;
    add_header Cache-Control "no-cache";
}

location ~ "^/(index\.html|app\.js|styles\.css|summary\.json|release\.json)$" {
    try_files $uri =404;
    add_header X-Atlas-Release $atlas_release always;
    add_header Cache-Control "no-cache";
}

location = /sparql {
    limit_req zone=atlas_sparql burst=40 nodelay;
    limit_req_status 429;
    client_max_body_size 64k;
    if ($request_method = OPTIONS) {
        add_header Access-Control-Allow-Origin "*";
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS";
        add_header Access-Control-Allow-Headers "Content-Type, Accept";
        return 204;
    }
    proxy_set_header Accept $atlas_sparql_accept;
    proxy_read_timeout 60s;
    proxy_hide_header Access-Control-Allow-Origin;
    add_header Access-Control-Allow-Origin "*" always;
    add_header X-Atlas-Release $atlas_release always;
    proxy_pass http://$atlas_qlever;
}

# Data IRIs http://phenomebrowser.net/flopo/<namespace>/<id>.
location ~ "^/taxon/([A-Za-z0-9._~-]+)$" {
    error_page 418 = @describe;
    if ($atlas_rdf_type) { return 418; }
    return 303 $http_x_forwarded_prefix/#/taxon/$1;
}

location ~ "^/[a-z-]+/[A-Za-z0-9._~/-]+$" {
    error_page 418 = @describe;
    if ($atlas_rdf_type) { return 418; }
    return 303 $http_x_forwarded_prefix/#/query?describe=http%3A%2F%2Fphenomebrowser.net%2Fflopo$uri;
}

location @describe {
    limit_req zone=atlas_sparql burst=40 nodelay;
    proxy_set_header Accept $atlas_rdf_type;
    proxy_hide_header Access-Control-Allow-Origin;
    add_header Access-Control-Allow-Origin "*" always;
    proxy_pass http://$atlas_qlever/?query=DESCRIBE%20%3Chttp%3A%2F%2Fphenomebrowser.net%2Fflopo$uri%3E;
}

location / {
    return 404;
}
