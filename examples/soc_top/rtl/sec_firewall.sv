// r1: correct
module sec_firewall #(parameter int KEYS = 2) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic [2:0]  prot,      // prot[1] = secure
    input  logic [31:0] addr,
    output logic        deny
);
    wire is_secure = ~prot[1];     // r2 changes this to prot[1] — a one-line bug
    assign deny = ~is_secure && addr[31];
endmodule
