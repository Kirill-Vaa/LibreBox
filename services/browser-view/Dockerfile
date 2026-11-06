FROM alpine:3.22 AS idle-screen

RUN apk add --no-cache \
    font-inter \
    imagemagick

COPY render-idle-screen.sh /tmp/render-idle-screen.sh

RUN sh /tmp/render-idle-screen.sh /idle-screen.png


FROM alpine:3.22

RUN apk add --no-cache \
    novnc \
    tini \
    websockify \
    x11vnc \
    xdpyinfo \
    xwallpaper \
    && mkdir -p /srv/web/browser \
    && cp -R /usr/share/novnc/app /usr/share/novnc/core /usr/share/novnc/vendor /usr/share/novnc/package.json /usr/share/novnc/vnc.html /srv/web/browser/ \
    && rm -rf /usr/share/novnc

COPY --from=idle-screen /idle-screen.png /usr/share/libre-box/idle-screen.png
COPY novnc/defaults.json novnc/mandatory.json /srv/web/browser/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh \
    && ln -s vnc.html /srv/web/browser/index.html

ENV DISPLAY=:99

USER 65534:65534

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:6080/browser/vnc.html \
        && xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1

ENTRYPOINT ["/sbin/tini", "-g", "--", "/usr/local/bin/entrypoint.sh"]