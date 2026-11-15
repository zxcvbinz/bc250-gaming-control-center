CFLAGS = -O2 -fPIC -shared -fvisibility=hidden -Wall -Wno-parentheses
PREFIX ?= $(HOME)/.local/lib/bc250

all: libbc250_vk.so libbc250_gl.so

libbc250_vk.so: vk_layer.c common.h
	$(CC) $(CFLAGS) -o $@ vk_layer.c -lpthread

libbc250_gl.so: gl_preload.c common.h
	$(CC) $(CFLAGS) -o $@ gl_preload.c -ldl -lpthread

install: all
	mkdir -p $(PREFIX)
	install -m 0755 libbc250_vk.so libbc250_gl.so $(PREFIX)/

clean:
	rm -f *.so
