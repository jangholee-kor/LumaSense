#include <assert.h>
#include <stdio.h>
#include "smc_network_guard.h"

int main(void) {
    assert(smc_network_line_bounded("{\"cmd\":\"ping\"}"));
    assert(smc_network_line_bounded("{\"text\":\"[[[[[[[[[[[ escaped \\\" quote\",\"cmd\":\"ping\"}"));
    assert(smc_network_line_bounded("{\"values\":[1,2,{\"a\":true}]}"));
    assert(!smc_network_line_bounded("[[[[[[[[[]]]]]]]]]"));
    assert(!smc_network_line_bounded("{\"cmd\":\"unterminated}"));
    assert(!smc_network_line_bounded("}"));
    puts("Network JSON recursion depth and quoted delimiter tests passed");
    return 0;
}
