// Two clock domains with a signal crossing between them.
module mixed_clocks (
    input  logic       clk_a,
    input  logic       clk_b,
    input  logic       d_in
);
    logic [7:0] a_reg, b_reg, c_reg, comb;

    always_ff @(posedge clk_a) begin a_reg <= d_in; end
    always_ff @(posedge clk_b) begin b_reg <= a_reg; end      // a_reg crosses
    assign comb = a_reg + 1;
    always_ff @(posedge clk_b) begin c_reg <= comb; end       // crosses via logic
endmodule
