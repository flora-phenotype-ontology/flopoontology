# Shared by the live and staging servers. The state file sets $atlas_root (the release's web
# directory), $atlas_qlever (127.0.0.1:<port> of its QLever container) and $atlas_release.

root $atlas_root;
charset utf-8;
absolute_redirect off;
add_header X-Atlas-Release $atlas_release always;

# The taxon list is three query results of 12-17 MB each; compressed they are about a tenth.
gzip on;
gzip_proxied any;
gzip_min_length 1024;
gzip_types application/sparql-results+json application/json application/javascript text/css text/csv
           text/tab-separated-values text/turtle application/n-triples;

location = / {
    try_files /index.html =404;
    add_header X-Atlas-Release $atlas_release always;
    add_header Cache-Control "no-cache";
}

location ~ "^/(index\.html|app\.js|styles\.css|summary\.json|release\.json|inaturalist\.json|places\.json|taxa\.json|country-taxa\.json|patterns\.json|attributes\.json|downloads\.json|precomputed-queries\.json|precomputed/[a-zA-Z]+\.json)$" {
    try_files $uri =404;
    add_header X-Atlas-Release $atlas_release always;
    add_header Cache-Control "no-cache";
}

# The description of the dataset (tools/atlas_metadata.py): VoID/DCAT, schema.org, versions.
location ~ "^/(void\.ttl|dataset\.jsonld|versions\.json)$" {
    try_files $uri =404;
    types { text/turtle ttl; application/ld+json jsonld; application/json json; }
    add_header X-Atlas-Release $atlas_release always;
    add_header Access-Control-Allow-Origin "*" always;
    add_header Cache-Control "no-cache";
}

# The dataset and its versions: the description to a program that asks for RDF, the Downloads
# page to a browser. Every version is described in the one file.
location ~ "^/(dataset|release/[0-9]+-[0-9]+)$" {
    if ($atlas_rdf_type) { rewrite ^ /void.ttl last; }
    return 303 $http_x_forwarded_prefix/#/downloads;
}

# country outlines of the Map page (an exact match, before the data IRIs below)
location = /data/countries.geojson {
    try_files $uri =404;
    default_type application/geo+json;
    add_header X-Atlas-Release $atlas_release always;
    add_header Cache-Control "public, max-age=86400";
}

# Bulk downloads of the release (tools/atlas_downloads.py): gzipped N-Quads and TSV tables.
# "^~" keeps the data-IRI patterns below from matching these paths.
location ^~ /downloads/ {
    root /srv/atlas/$atlas_release;
    types { text/plain txt cff; application/json json; application/gzip gz; text/turtle ttl; application/ld+json jsonld; }
    default_type application/octet-stream;
    gzip off;
    add_header X-Atlas-Release $atlas_release always;
    add_header Access-Control-Allow-Origin "*" always;
    add_header Cache-Control "no-cache";
}

# Votes on annotations: the feedback service (tools/deploy_atlas.sh starts it on 127.0.0.1:7010).
# It checks a voted record against this server's own QLever. No CORS: only this site may vote.
location ^~ /feedback/ {
    limit_req zone=atlas_feedback burst=30 nodelay;
    limit_req_status 429;
    client_max_body_size 8k;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Prefix $http_x_forwarded_prefix;
    proxy_set_header X-Forwarded-For "";
    proxy_set_header X-Atlas-Client $atlas_voter;
    proxy_set_header X-Atlas-Sparql http://$atlas_qlever/;
    proxy_set_header X-Atlas-Release $atlas_release;
    proxy_read_timeout 30s;
    add_header X-Atlas-Release $atlas_release always;
    add_header Cache-Control "no-store" always;
    proxy_pass http://127.0.0.1:7010;
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
