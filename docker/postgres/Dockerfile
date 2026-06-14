FROM postgres:16-alpine AS prepared

RUN apk upgrade --no-cache && \
    apk add --no-cache su-exec && \
    rm -f /usr/local/bin/gosu && \
    ln -s /sbin/su-exec /usr/local/bin/gosu

# Flatten the runtime rootfs so the removed vulnerable gosu binary is not
# retained in an inaccessible lower image layer.
FROM scratch

COPY --from=prepared / /

ENV LANG=en_US.utf8 \
    PG_MAJOR=16 \
    PG_VERSION=16.14 \
    PG_SHA256=f6d077142737920858ce958ccdb75c6ee137a63b5b0853c70693d401ac7e3471 \
    DOCKER_PG_LLVM_DEPS="llvm19-dev clang19" \
    PGDATA=/var/lib/postgresql/data

WORKDIR /
VOLUME /var/lib/postgresql/data
EXPOSE 5432
ENTRYPOINT ["docker-entrypoint.sh"]
STOPSIGNAL SIGINT
CMD ["postgres"]
