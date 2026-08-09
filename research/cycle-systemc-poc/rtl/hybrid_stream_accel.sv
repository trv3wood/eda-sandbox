module sample_transform(
  input  logic [15:0] in_data,
  input  logic [15:0] scale,
  input  logic [15:0] bias,
  output logic [31:0] term
);
  assign term = in_data * scale + {16'd0, bias};
endmodule

module stream_accumulator(
  input  logic        clk,
  input  logic        reset_n,
  input  logic        start,
  input  logic [7:0]  length,
  input  logic        in_valid,
  output logic        in_ready,
  input  logic [31:0] term,
  output logic        out_valid,
  input  logic        out_ready,
  output logic [31:0] result
);
  logic active;
  logic [7:0] remaining;
  logic [31:0] accumulator;

  assign in_ready = active && !out_valid;
  assign result = accumulator;

  always_ff @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      active <= 1'b0;
      remaining <= '0;
      accumulator <= '0;
      out_valid <= 1'b0;
    end else begin
      if (out_valid && out_ready) begin
        out_valid <= 1'b0;
        active <= 1'b0;
      end
      if (start && !active) begin
        active <= 1'b1;
        remaining <= length;
        accumulator <= '0;
      end else if (in_valid && in_ready) begin
        accumulator <= accumulator + term;
        remaining <= remaining - 8'd1;
        if (remaining == 8'd1)
          out_valid <= 1'b1;
      end
    end
  end
endmodule

// 顶层仅表达模块层次与连线，行为全部留在可替换分区内。
module hybrid_stream_accel(
  input  logic        clk,
  input  logic        reset_n,
  input  logic        start,
  input  logic [7:0]  length,
  input  logic [15:0] scale,
  input  logic [15:0] bias,
  input  logic        in_valid,
  output logic        in_ready,
  input  logic [15:0] in_data,
  output logic        out_valid,
  input  logic        out_ready,
  output logic [31:0] result
);
  logic [31:0] term;

  sample_transform transform (
    .in_data(in_data),
    .scale(scale),
    .bias(bias),
    .term(term)
  );

  stream_accumulator accumulator (
    .clk(clk),
    .reset_n(reset_n),
    .start(start),
    .length(length),
    .in_valid(in_valid),
    .in_ready(in_ready),
    .term(term),
    .out_valid(out_valid),
    .out_ready(out_ready),
    .result(result)
  );
endmodule
