FROM safarov/freeswitch:latest

# Default config is replaced by volume mount
# TLS certs are generated at runtime by entrypoint

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5060/udp 5060/tcp 5061/tcp 7443/tcp 8021/tcp 16384-32768/udp

ENTRYPOINT ["/entrypoint.sh"]
CMD ["freeswitch", "-nonat", "-c"]
