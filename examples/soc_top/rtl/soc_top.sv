module soc_top (
    input logic clk, rst_n
);
    logic dma_deny, sec_deny;
    dma  u_dma  (.clk(clk), .rst_n(rst_n), .deny(dma_deny));
    sec_firewall u_sec (.clk(clk), .rst_n(rst_n), .prot(3'b000), .addr(32'h0), .deny(sec_deny));
endmodule
