#include "smc_network_guard.h"

/* cJSON's default recursive depth is too large for an embedded task stack. */
bool smc_network_line_bounded(const char *line) {
    unsigned depth = 0;
    bool quoted = false, escaped = false;
    for (const char *cursor = line; *cursor; ++cursor) {
        char value = *cursor;
        if (quoted) {
            if (escaped) escaped = false;
            else if (value == '\\') escaped = true;
            else if (value == '"') quoted = false;
        } else if (value == '"') quoted = true;
        else if (value == '{' || value == '[') { if (++depth > 8) return false; }
        else if (value == '}' || value == ']') { if (!depth) return false; --depth; }
    }
    return !quoted && depth == 0;
}
